"""Model-to-IR generation for constraint-driven geometry scenes."""

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
from aetherviz_service.aetherviz.ir.constraint_geometry.contract import (
    CONSTRAINT_GEOMETRY_IR_MAX_CHARS,
    CONSTRAINT_GEOMETRY_IR_VERSION,
    constraint_geometry_ir_candidates_response_schema,
    constraint_geometry_ir_response_schema,
    parse_constraint_geometry_ir,
    parse_constraint_geometry_ir_candidates,
    rank_constraint_geometry_ir_candidates,
)
from aetherviz_service.aetherviz.ir.constraint_geometry.runtime import assemble_constraint_geometry_business_html

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""你是通用约束几何 IR 生成器。只输出 JSON，version 固定为 {CONSTRAINT_GEOMETRY_IR_VERSION}。
IR 只表达参数驱动的欧氏几何语义。服务端负责 SVG、坐标映射、布局、动画控制和 iframe Runtime；不得输出 HTML、CSS、JavaScript、像素坐标或动画循环。
viewport 是数学坐标范围。points 的 x/y 与 circles.radius 使用受限表达式：数值、{{"state":"计划变量"}} 或 {{"op":"操作","args":[...]}}；操作只允许 add/sub/mul/div/pow/min/max/neg/abs/sqrt/sin/cos/tan/asin/acos/atan2/deg_to_rad，三角函数输入使用弧度。
lines 只引用已声明点；circles 只引用已声明圆心。angles 用 from、vertex、to 引用三个不同点并输出实时角度。loci 只引用动点，max_samples 不超过 800，不生成静态轨迹坐标。
points[].drag 只允许绑定计划状态：x/y 沿单轴拖动；angle_on_circle 引用圆并把指针投影为圆周角；segment_parameter 引用线段并把投影比例映射到状态范围。它是有界状态映射，不是通用约束求解器。
constraints 只允许 coincident、horizontal、vertical、parallel、perpendicular、equal_length、point_on_circle、midpoint、collinear、tangent、equal_angle、supplementary，且 tolerance 不超过 0.001。tangent 依次引用切线、圆、切点，服务端同时验证切点在圆和线上且半径垂直切线；equal_angle/supplementary 引用两个 angle。
animation.variable 必须引用 allowed_state_variables 中一个变量；服务端覆盖 from/to 并在上下界及内部状态验证全部约束。不要使用近似坐标冒充严格关系，应从同一表达式构造依赖点。
该 IR 不覆盖割补重排、离散正多边形收敛、函数坐标图或通用物理运动。所有学生可见说明使用简体中文，数学点名可使用 A、B、C、O。IR 不超过 {CONSTRAINT_GEOMETRY_IR_MAX_CHARS} 字符。"""


def stream_generate_constraint_geometry_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError("约束几何 IR 生成失败，未配置可用模型", code="model_unavailable")
    yield build_html_progress_payload(
        [
            {"content": "生成约束几何 IR", "status": "in_progress"},
            {"content": "验证几何不变量", "status": "pending"},
            {"content": "编译服务端几何运行时", "status": "pending"},
        ]
    )
    raw = _invoke(
        _prompt(topic, plan),
        constraint_geometry_ir_candidates_response_schema(),
        CONSTRAINT_GEOMETRY_IR_MAX_CHARS * 2 + 1024,
    )
    try:
        ranking = rank_constraint_geometry_ir_candidates(parse_constraint_geometry_ir_candidates(raw), plan)
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
            constraint_geometry_ir_response_schema(),
            CONSTRAINT_GEOMETRY_IR_MAX_CHARS + 512,
        )
        try:
            ranking = rank_constraint_geometry_ir_candidates([parse_constraint_geometry_ir(repaired)], plan)
        except (TypeError, ValueError, json.JSONDecodeError):
            ranking = {"ok": False}
    if not ranking["ok"]:
        logger.warning("constraint geometry IR invalid; falling back to direct HTML")
        for item in stream_generate_html(topic, plan):
            yield (
                replace(item, degraded=True, generation_fallback="constraint_geometry_ir_invalid")
                if isinstance(item, HtmlStreamResult)
                else item
            )
        return
    yield build_html_progress_payload(
        [
            {"content": "生成约束几何 IR", "status": "completed"},
            {"content": "验证几何不变量", "status": "completed"},
            {"content": "编译服务端几何运行时", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(
        html=assemble_constraint_geometry_business_html(ranking["selected_ir"], plan, topic),
        degraded=degraded,
        truncated=False,
        strategy="constraint_geometry_ir",
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
        logger.warning("strict constraint geometry schema unavailable; using JSON mode: %s", exc)
        raw = "".join(extract_llm_text(chunk) for chunk in create_chat_model("scene").stream(messages))[:limit]
    return raw


def _prompt(topic: str, plan: dict[str, Any]) -> str:
    return '严格输出 {"candidates":[IR1,IR2]}，两个候选使用不同但通用的构造依赖组织。' + json.dumps(
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
    return "只修复报告中的确定性错误，保持对象身份和教学语义，输出完整单个 IR；不得放宽 tolerance。" + json.dumps(
        {
            "topic": topic,
            "variables": (plan.get("interactive_spec") or {}).get("variables", []),
            "candidate": ranking.get("repair_candidate"),
            "report": ranking.get("repair_report"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
