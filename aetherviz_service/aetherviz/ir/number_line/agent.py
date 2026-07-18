"""Model-to-IR generation for deterministic number-line scenes."""

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
from aetherviz_service.aetherviz.ir.number_line.contract import (
    NUMBER_LINE_IR_MAX_CHARS,
    NUMBER_LINE_IR_VERSION,
    number_line_ir_candidates_response_schema,
    number_line_ir_response_schema,
    parse_number_line_ir,
    parse_number_line_ir_candidates,
    rank_number_line_ir_candidates,
)
from aetherviz_service.aetherviz.ir.number_line.runtime import assemble_number_line_business_html

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""你是一维数学数轴 IR 生成器。只输出 JSON；version 固定为 {NUMBER_LINE_IR_VERSION}。
IR 只表达数学语义：固定 domain、多条语义轨道，以及点、区间、射线、距离和有向位移。服务端统一负责 960×500 SVG、刻度、响应式布局、控件、播放和 iframe Runtime。不得输出 SVG 坐标、HTML、CSS、JavaScript 或 requestAnimationFrame。
表达式只能是有限数值、{{"state":"计划变量"}}，或 {{"op":"add|sub|mul|div|min|max|neg|abs","args":[...]}}。所有表达式在计划变量最小值、默认值和最大值下都必须位于 domain 内；区间 start 不得大于 end。
points 用 endpoint=open/closed；intervals 分别声明左右端点；rays 声明 boundary、left/right 和端点；distances 表达两值绝对距离；movements 表达 start 与 delta。每个对象引用已声明 track，id 全局唯一，颜色为 #RRGGBB。
animation.variable 必须引用计划变量，服务端会覆盖 from/to。多变量场景必须用 0~1 关键帧覆盖全部变量；单变量 keyframes 输出空数组。invariants 至少声明一个，并引用已有对象。
只覆盖一维数轴，不输出坐标曲线、二维几何或统计图。学生可见标签使用简体中文。IR 不超过 {NUMBER_LINE_IR_MAX_CHARS} 字符。"""


def stream_generate_number_line_html(topic: str, plan: dict[str, Any]) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError("数轴 IR 生成失败，未配置可用模型", code="model_unavailable")
    yield build_html_progress_payload(
        [
            {"content": "生成数轴 IR", "status": "in_progress"},
            {"content": "验证端点、区间与数值关系", "status": "pending"},
            {"content": "编译服务端数轴运行时", "status": "pending"},
        ]
    )
    raw = _invoke(
        _prompt(topic, plan, candidates=True),
        number_line_ir_candidates_response_schema(),
        NUMBER_LINE_IR_MAX_CHARS * 2 + 1024,
    )
    try:
        ranking = rank_number_line_ir_candidates(parse_number_line_ir_candidates(raw), plan)
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
            number_line_ir_response_schema(),
            NUMBER_LINE_IR_MAX_CHARS + 512,
        )
        try:
            ranking = rank_number_line_ir_candidates([parse_number_line_ir(repaired)], plan)
        except (TypeError, ValueError, json.JSONDecodeError):
            ranking = {"ok": False}
    if not ranking["ok"]:
        logger.warning("number-line IR invalid; falling back to direct HTML")
        for item in stream_generate_html(topic, plan):
            yield (
                replace(item, degraded=True, generation_fallback="number_line_ir_invalid")
                if isinstance(item, HtmlStreamResult)
                else item
            )
        return
    yield build_html_progress_payload(
        [
            {"content": "生成数轴 IR", "status": "completed"},
            {"content": "验证端点、区间与数值关系", "status": "completed"},
            {"content": "编译服务端数轴运行时", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(
        html=assemble_number_line_business_html(ranking["selected_ir"], plan, topic),
        degraded=degraded,
        truncated=False,
        strategy="number_line_ir",
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
        logger.warning("strict number-line schema unavailable; using JSON mode: %s", exc)
        raw = "".join(extract_llm_text(chunk) for chunk in create_chat_model("scene").stream(messages))[:limit]
    return raw


def _prompt(topic: str, plan: dict[str, Any], *, candidates: bool) -> str:
    payload = {
        "topic": topic,
        "goal": plan.get("goal"),
        "allowed_state_variables": (plan.get("interactive_spec") or {}).get("variables", []),
        "representation_spec": plan.get("representation_spec"),
        "teaching_flow": plan.get("teaching_flow"),
    }
    prefix = (
        '严格输出 {"candidates":[IR1,IR2]}，两个候选使用不同但等价的一维表征组织。'
        if candidates
        else "输出完整单个 IR。"
    )
    return prefix + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _repair_prompt(topic: str, plan: dict[str, Any], ranking: dict[str, Any]) -> str:
    return "只修复确定性错误，保留一维数轴语义并输出完整单个 IR。" + json.dumps(
        {
            "topic": topic,
            "variables": (plan.get("interactive_spec") or {}).get("variables", []),
            "candidate": ranking.get("repair_candidate"),
            "report": ranking.get("repair_report"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
