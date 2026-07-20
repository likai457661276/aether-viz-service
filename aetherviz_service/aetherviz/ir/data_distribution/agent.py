"""Model-to-IR generation for deterministic data distribution scenes."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text, has_primary_llm_config
from aetherviz_service.aetherviz.contracts.html_stream import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.ir.data_distribution.contract import (
    DATA_DISTRIBUTION_IR_MAX_CHARS,
    DATA_DISTRIBUTION_IR_VERSION,
    data_distribution_ir_candidates_response_schema,
    data_distribution_ir_response_schema,
    parse_data_distribution_ir,
    parse_data_distribution_ir_candidates,
    rank_data_distribution_ir_candidates,
)
from aetherviz_service.aetherviz.ir.data_distribution.runtime import assemble_data_distribution_business_html

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""你是通用数据分布 IR 生成器。只输出 JSON，version 固定为 {DATA_DISTRIBUTION_IR_VERSION}。
IR 只表达原始数据、字段语义、图表映射和需要展示的统计量。服务端负责表格、SVG、坐标轴、响应式布局、动画生命周期、分箱、四分位数和线性回归；不得输出 HTML、CSS、JavaScript、SVG 坐标或已经计算好的统计结果。
fields 定义 number/category 字段。每一行 rows.cells 必须且只能覆盖全部字段；number 使用数值、{{"state":"计划变量"}} 或受限表达式，category 只用简体中文字符串。固定样本在状态变化时保持 row id 和分类值不变。
charts 只允许 table、bar、line、scatter、histogram、box：bar 使用 category_field/value_field；line/scatter 使用 x_field/y_field；histogram 使用 value_field/bin_width；box 使用 value_field，可选 group_field。数值轴只能引用 number 字段。直方图在全部状态下最多 80 箱。
metrics 只声明 count、sum、mean、median、variance、standard_deviation、minimum、maximum、q1、q3、iqr、linear_regression；除回归使用 x_field/y_field 外均使用 field。sample=true 表示样本方差或样本标准差。不要输出 metric value。
表达式操作只允许 add/sub/mul/div/pow/min/max/neg/abs/sqrt/round/floor/ceil。animation.variable 必须来自 allowed_state_variables，服务端会覆盖范围并在变量边界验证所有数据与派生量。
首版不生成随机样本、不累计随机试验，也不计算连续概率密度或曲线下面积；遇到这些目标必须判定为不支持，不得输出近似替代。所有学生可见文字使用简体中文。IR 不超过 {DATA_DISTRIBUTION_IR_MAX_CHARS} 字符。"""


def stream_generate_data_distribution_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError("数据分布 IR 生成失败，未配置可用模型", code="model_unavailable")
    yield build_html_progress_payload(
        [
            {"content": "生成数据分布 IR", "status": "in_progress"},
            {"content": "验证数据与派生统计量", "status": "pending"},
            {"content": "编译服务端图表运行时", "status": "pending"},
        ]
    )
    raw = _invoke(
        _prompt(topic, plan),
        data_distribution_ir_candidates_response_schema(),
        DATA_DISTRIBUTION_IR_MAX_CHARS * 2 + 1024,
    )
    try:
        ranking = rank_data_distribution_ir_candidates(parse_data_distribution_ir_candidates(raw), plan)
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
            _repair_prompt(topic, plan, ranking),
            data_distribution_ir_response_schema(),
            DATA_DISTRIBUTION_IR_MAX_CHARS + 512,
        )
        try:
            ranking = rank_data_distribution_ir_candidates([parse_data_distribution_ir(repaired)], plan)
        except (TypeError, ValueError, json.JSONDecodeError):
            ranking = {"ok": False}
    if not ranking["ok"]:
        raise HtmlGenerationError(
            "数据分布 IR 未通过确定性校验，已停止生成",
            code="ir_generation_failed",
            detail="data_distribution_ir_invalid",
        )
    yield build_html_progress_payload(
        [
            {"content": "生成数据分布 IR", "status": "completed"},
            {"content": "验证数据与派生统计量", "status": "completed"},
            {"content": "编译服务端图表运行时", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(
        html=assemble_data_distribution_business_html(ranking["selected_ir"], plan, topic),
        degraded=degraded,
        truncated=False,
        strategy="data_distribution_ir",
        source_chars=len(raw),
        output_chars=len(raw),
    )


def _invoke(prompt: str, schema: dict[str, Any], limit: int) -> str:
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    raw = ""
    try:
        model = create_chat_model("scene", response_schema=schema)
        for chunk in model.stream(messages):
            raw += extract_llm_text(chunk)
            if len(raw) > limit:
                break
    except Exception as exc:
        logger.warning("strict data distribution schema unavailable; using JSON mode: %s", exc)
        raw = "".join(extract_llm_text(chunk) for chunk in create_chat_model("scene").stream(messages))[:limit]
    return raw


def _prompt(topic: str, plan: dict[str, Any]) -> str:
    return '严格输出 {"candidates":[IR1,IR2]}，两个候选共享同一数学数据但使用不同的通用图表组合。' + json.dumps(
        {
            "topic": topic,
            "goal": plan.get("goal"),
            "allowed_state_variables": (plan.get("interactive_spec") or {}).get("variables", []),
            "representation_spec": plan.get("representation_spec"),
            "discipline_spec": plan.get("discipline_spec"),
            "teaching_flow": plan.get("teaching_flow"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _repair_prompt(topic: str, plan: dict[str, Any], ranking: dict[str, Any]) -> str:
    return "只修复报告中的确定性错误，保持原始样本身份和教学语义，输出完整单个 IR；不得预计算统计结果。" + json.dumps(
        {
            "topic": topic,
            "variables": (plan.get("interactive_spec") or {}).get("variables", []),
            "candidate": ranking.get("repair_candidate"),
            "report": ranking.get("repair_report"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
