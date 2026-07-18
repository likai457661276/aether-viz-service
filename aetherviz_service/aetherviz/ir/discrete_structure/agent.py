"""Model-to-IR generation for finite discrete structures."""

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
from aetherviz_service.aetherviz.ir.discrete_structure.contract import (
    DISCRETE_STRUCTURE_IR_MAX_CHARS,
    DISCRETE_STRUCTURE_IR_VERSION,
    discrete_structure_ir_candidates_response_schema,
    discrete_structure_ir_response_schema,
    parse_discrete_structure_ir,
    parse_discrete_structure_ir_candidates,
    rank_discrete_structure_ir_candidates,
)
from aetherviz_service.aetherviz.ir.discrete_structure.runtime import assemble_discrete_structure_business_html

logger = logging.getLogger(__name__)
SYSTEM_PROMPT = f"""你是离散结构 IR 生成器，只输出 JSON，version 固定为 {DISCRETE_STRUCTURE_IR_VERSION}。nodes 的 id 在全部阶段保持稳定，order 唯一；edges 只能连接已声明节点；visible_from/visible_to 是 0~1 阶段区间。sets 只引用节点；sequences 必须显式给出有限项和递推文字。views 只允许 graph、tree、set、sequence、permutation；tree 必须是有向无环单根树，每个非根节点入度为 1。服务端负责布局、拓扑显隐和动画，不得输出坐标、HTML、JavaScript、SVG 或运行期新增节点。首版不执行最短路、最大流等图算法，也不是自由图编辑器。所有文字使用简体中文，IR 不超过 {DISCRETE_STRUCTURE_IR_MAX_CHARS} 字符。"""


def stream_generate_discrete_structure_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError("离散结构 IR 生成失败，未配置可用模型", code="model_unavailable")
    yield build_html_progress_payload(
        [
            {"content": "生成离散结构 IR", "status": "in_progress"},
            {"content": "验证身份与拓扑", "status": "pending"},
            {"content": "编译离散结构运行时", "status": "pending"},
        ]
    )
    raw = _invoke(
        _prompt(topic, plan),
        discrete_structure_ir_candidates_response_schema(),
        DISCRETE_STRUCTURE_IR_MAX_CHARS * 2 + 1024,
    )
    try:
        ranking = rank_discrete_structure_ir_candidates(parse_discrete_structure_ir_candidates(raw), plan)
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
            discrete_structure_ir_response_schema(),
            DISCRETE_STRUCTURE_IR_MAX_CHARS + 512,
        )
        try:
            ranking = rank_discrete_structure_ir_candidates([parse_discrete_structure_ir(repaired)], plan)
        except (TypeError, ValueError, json.JSONDecodeError):
            ranking = {"ok": False}
    if not ranking["ok"]:
        logger.warning("discrete structure IR invalid; falling back to direct HTML")
        for item in stream_generate_html(topic, plan):
            yield (
                replace(item, degraded=True, generation_fallback="discrete_structure_ir_invalid")
                if isinstance(item, HtmlStreamResult)
                else item
            )
        return
    yield build_html_progress_payload(
        [
            {"content": "生成离散结构 IR", "status": "completed"},
            {"content": "验证身份与拓扑", "status": "completed"},
            {"content": "编译离散结构运行时", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(
        html=assemble_discrete_structure_business_html(ranking["selected_ir"], plan, topic),
        degraded=degraded,
        truncated=False,
        strategy="discrete_structure_ir",
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
        logger.warning("strict discrete schema unavailable; using JSON mode: %s", exc)
        raw = "".join(extract_llm_text(chunk) for chunk in create_chat_model("scene").stream(messages))[:limit]
    return raw


def _prompt(topic: str, plan: dict[str, Any]) -> str:
    return '严格输出 {"candidates":[IR1,IR2]}，两个候选共享节点身份但采用不同视图组合。' + json.dumps(
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
    return "只修复报告中的确定性错误，保持节点身份和教学语义，输出完整单个 IR。" + json.dumps(
        {"topic": topic, "candidate": ranking.get("repair_candidate"), "report": ranking.get("repair_report")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
