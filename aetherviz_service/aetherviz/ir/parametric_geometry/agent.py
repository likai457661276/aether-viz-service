"""Model-to-IR generation for discrete parametric geometry scenes."""

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
from aetherviz_service.aetherviz.ir.parametric_geometry.contract import (
    PARAMETRIC_GEOMETRY_IR_MAX_CHARS,
    PARAMETRIC_GEOMETRY_IR_VERSION,
    parametric_geometry_ir_candidates_response_schema,
    parametric_geometry_ir_response_schema,
    parse_parametric_geometry_ir,
    parse_parametric_geometry_ir_candidates,
    rank_parametric_geometry_ir_candidates,
)
from aetherviz_service.aetherviz.ir.parametric_geometry.runtime import assemble_parametric_geometry_business_html

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""你是参数几何 IR 生成器。只输出 JSON；version 固定为 {PARAMETRIC_GEOMETRY_IR_VERSION}。
该 IR 只覆盖离散边数驱动的圆、内接/外切正多边形、周长和误差收敛。不能表达时仍输出最接近计划的合法对象，服务端会安全降级。
state.variable 必须引用 allowed_state_variables 中一个离散变量，范围由服务端覆盖；circle.radius 是数学半径；polygons 最多两个，mode 只能是 inscribed/circumscribed；measures 可选 circle_circumference、polygon_perimeter、absolute_error、relative_error，非圆测量必须引用 polygon id；invariants 至少包含 regular_polygon，内接图形必须包含 vertex_on_circle，声明 monotonic_convergence 时必须有误差测量。
服务端统一负责 SVG viewBox、预分配最大节点、响应式布局、共享 AetherVizAnimationController、play/pause/reset/setSpeed 和 iframe runtime。不得输出像素坐标、脚本、HTML、CSS 或 requestAnimationFrame。所有学生可见标签使用简体中文。IR 不超过 {PARAMETRIC_GEOMETRY_IR_MAX_CHARS} 字符。"""


def stream_generate_parametric_geometry_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError("参数几何 IR 生成失败，未配置可用模型", code="model_unavailable")
    yield build_html_progress_payload(
        [
            {"content": "生成参数几何 IR", "status": "in_progress"},
            {"content": "验证几何与收敛不变量", "status": "pending"},
            {"content": "编译服务端几何运行时", "status": "pending"},
        ]
    )
    raw = _invoke(
        _prompt(topic, plan, candidates=True),
        parametric_geometry_ir_candidates_response_schema(),
        PARAMETRIC_GEOMETRY_IR_MAX_CHARS * 2 + 1024,
    )
    try:
        ranking = rank_parametric_geometry_ir_candidates(parse_parametric_geometry_ir_candidates(raw), plan)
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
            parametric_geometry_ir_response_schema(),
            PARAMETRIC_GEOMETRY_IR_MAX_CHARS + 512,
        )
        try:
            ranking = rank_parametric_geometry_ir_candidates([parse_parametric_geometry_ir(repaired)], plan)
        except (TypeError, ValueError, json.JSONDecodeError):
            ranking = {"ok": False}
    if not ranking["ok"]:
        logger.warning("parametric geometry IR invalid; falling back to direct HTML")
        for item in stream_generate_html(topic, plan):
            yield (
                replace(item, degraded=True, generation_fallback="parametric_geometry_ir_invalid")
                if isinstance(item, HtmlStreamResult)
                else item
            )
        return
    yield build_html_progress_payload(
        [
            {"content": "生成参数几何 IR", "status": "completed"},
            {"content": "验证几何与收敛不变量", "status": "completed"},
            {"content": "编译服务端几何运行时", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(
        html=assemble_parametric_geometry_business_html(ranking["selected_ir"], plan, topic),
        degraded=degraded,
        truncated=False,
        strategy="parametric_geometry_ir",
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
        logger.warning("strict parametric geometry schema unavailable; using JSON mode: %s", exc)
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
        '严格输出 {"candidates":[IR1,IR2]}，两个候选使用不同的内接/外切对照组织。'
        if candidates
        else "输出完整单个 IR。"
    )
    return prefix + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _repair_prompt(topic: str, plan: dict[str, Any], ranking: dict[str, Any]) -> str:
    return "只修复确定性错误，输出完整单个 IR。" + json.dumps(
        {
            "topic": topic,
            "variables": (plan.get("interactive_spec") or {}).get("variables", []),
            "candidate": ranking.get("repair_candidate"),
            "report": ranking.get("repair_report"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
