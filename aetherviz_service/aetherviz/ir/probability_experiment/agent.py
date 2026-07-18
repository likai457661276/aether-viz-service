"""Model-to-IR generation for finite probability experiments."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_primary_llm_config
from aetherviz_service.aetherviz.contracts.html_stream import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.generate.html_agent import stream_generate_html
from aetherviz_service.aetherviz.ir.probability_experiment.contract import (
    PROBABILITY_EXPERIMENT_IR_MAX_CHARS,
    PROBABILITY_EXPERIMENT_IR_VERSION,
    parse_probability_experiment_ir,
    parse_probability_experiment_ir_candidates,
    probability_experiment_ir_candidates_response_schema,
    probability_experiment_ir_response_schema,
    rank_probability_experiment_ir_candidates,
)
from aetherviz_service.aetherviz.ir.probability_experiment.runtime import assemble_probability_experiment_business_html

logger = logging.getLogger(__name__)
SYSTEM_PROMPT = f"""你是有限概率试验 IR 生成器，只输出 JSON，version 固定为 {PROBABILITY_EXPERIMENT_IR_VERSION}。outcomes 声明完整且互斥的有限样本点、正权重和 1~4 层路径；events 只能引用样本点 id。views 只允许 sample_space、frequency_chart、probability_tree，频率图必须引用事件。seed 必须固定，随机序列、累计频率、理论概率、树图坐标和动画均由服务端生成；不得输出预计算样本、概率结果、HTML、JavaScript 或 SVG。首版不支持连续分布、无限样本空间、马尔可夫链或贝叶斯网络。所有文字使用简体中文，IR 不超过 {PROBABILITY_EXPERIMENT_IR_MAX_CHARS} 字符。"""


def stream_generate_probability_experiment_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError("概率试验 IR 生成失败，未配置可用模型", code="model_unavailable")
    yield build_html_progress_payload(
        [
            {"content": "生成概率试验 IR", "status": "in_progress"},
            {"content": "验证样本空间与事件", "status": "pending"},
            {"content": "编译随机试验运行时", "status": "pending"},
        ]
    )
    raw = _invoke(
        _prompt(topic, plan),
        probability_experiment_ir_candidates_response_schema(),
        PROBABILITY_EXPERIMENT_IR_MAX_CHARS * 2 + 1024,
    )
    try:
        ranking = rank_probability_experiment_ir_candidates(parse_probability_experiment_ir_candidates(raw), plan)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        ranking = {
            "ok": False,
            "repair_candidate": raw,
            "repair_report": {"errors": [{"type": type(exc).__name__, "message": str(exc)}]},
        }
    degraded = False
    if not ranking["ok"]:
        degraded = True
        repaired = _invoke(
            _repair_prompt(topic, ranking),
            probability_experiment_ir_response_schema(),
            PROBABILITY_EXPERIMENT_IR_MAX_CHARS + 512,
        )
        try:
            ranking = rank_probability_experiment_ir_candidates([parse_probability_experiment_ir(repaired)], plan)
        except (TypeError, ValueError, json.JSONDecodeError):
            ranking = {"ok": False}
    if not ranking["ok"]:
        logger.warning("probability experiment IR invalid; falling back to direct HTML")
        for item in stream_generate_html(topic, plan):
            yield (
                replace(item, degraded=True, generation_fallback="probability_experiment_ir_invalid")
                if isinstance(item, HtmlStreamResult)
                else item
            )
        return
    yield build_html_progress_payload(
        [
            {"content": "生成概率试验 IR", "status": "completed"},
            {"content": "验证样本空间与事件", "status": "completed"},
            {"content": "编译随机试验运行时", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(
        html=assemble_probability_experiment_business_html(ranking["selected_ir"], plan, topic),
        degraded=degraded,
        truncated=False,
        strategy="probability_experiment_ir",
        source_chars=len(raw),
        output_chars=len(raw),
    )


def _invoke(prompt: str, schema: dict[str, Any], limit: int) -> str:
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    raw = ""
    try:
        for chunk in create_chat_model("scene", response_schema=schema).stream(messages):
            raw += extract_llm_text(chunk)
            if len(raw) > limit:
                break
    except Exception as exc:
        logger.warning("strict probability schema unavailable; using JSON mode: %s", exc)
        raw = "".join(extract_llm_text(chunk) for chunk in create_chat_model("scene").stream(messages))[:limit]
    return raw


def _prompt(topic: str, plan: dict[str, Any]) -> str:
    return '严格输出 {"candidates":[IR1,IR2]}，两个候选共享样本空间但采用不同视图组合。' + json.dumps(
        {
            "topic": topic,
            "goal": plan.get("goal"),
            "allowed_state_variables": (plan.get("interactive_spec") or {}).get("variables", []),
            "representation_spec": plan.get("representation_spec"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _repair_prompt(topic: str, ranking: dict[str, Any]) -> str:
    return "只修复报告中的确定性错误，保持样本空间和事件语义，输出完整单个 IR。" + json.dumps(
        {"topic": topic, "candidate": ranking.get("repair_candidate"), "report": ranking.get("repair_report")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
