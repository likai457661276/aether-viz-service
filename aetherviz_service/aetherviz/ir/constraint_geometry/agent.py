"""Model-to-IR generation for constraint-driven geometry scenes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.model_factory import has_primary_llm_config
from aetherviz_service.aetherviz.contracts.html_stream import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.ir.constraint_geometry.contract import (
    CONSTRAINT_GEOMETRY_IR_MAX_CHARS,
    CONSTRAINT_GEOMETRY_IR_VERSION,
    constraint_geometry_ir_candidates_response_schema,
    constraint_geometry_ir_response_schema,
    parse_constraint_geometry_ir,
    parse_constraint_geometry_ir_candidates,
    rank_constraint_geometry_ir_candidates,
    repair_constraint_geometry_ir,
)
from aetherviz_service.aetherviz.ir.constraint_geometry.runtime import assemble_constraint_geometry_business_html
from aetherviz_service.aetherviz.ir.stream import stream_ir_json

SYSTEM_PROMPT = f"""你是通用约束几何 IR 生成器。只输出 JSON，version 固定为 {CONSTRAINT_GEOMETRY_IR_VERSION}。
IR 只表达参数驱动的欧氏几何语义。服务端负责 SVG、坐标映射、布局、动画控制和 iframe Runtime；不得输出 HTML、CSS、JavaScript、像素坐标或动画循环。
viewport 是数学坐标范围。points 的 x/y 与 circles.radius 使用受限表达式：数值、{{"state":"计划变量"}} 或 {{"op":"操作","args":[...]}}；操作只允许 add/sub/mul/div/pow/min/max/neg/abs/sqrt/sin/cos/tan/asin/acos/atan2/deg_to_rad，三角函数输入使用弧度。
{{"state":"..."}} 只能引用 allowed_state_variables 中的变量名；禁止 B.x、A.y、点 id、线 id 或其他未声明状态。若需要引用其他点坐标，应直接复用同一表达式或数值，不要写成点字段别名。
lines 只引用已声明点；circles 只引用已声明圆心。angles 用 from、vertex、to 引用三个不同点并输出实时角度。loci 只引用动点，max_samples 不超过 800，不生成静态轨迹坐标。
points[].drag 只允许绑定计划状态：x/y 沿单轴拖动；angle_on_circle 引用圆并把指针投影为圆周角；segment_parameter 引用线段并把投影比例映射到状态范围。若声明 drag，被拖点对应坐标必须直接或间接依赖同一 state；否则不要输出 drag。
constraints 只允许 coincident、horizontal、vertical、parallel、perpendicular、equal_length、point_on_circle、midpoint、collinear、tangent、equal_angle、supplementary，且 tolerance 不超过 0.001。
refs 类型必须匹配：coincident/horizontal/vertical 引用两点；parallel/perpendicular/equal_length 引用两线；midpoint/collinear 引用三点；point_on_circle 引用点与圆；tangent 依次引用切线、圆、切点；equal_angle/supplementary 引用两个 angle。不要把点-线写成 coincident。
animation.variable 必须引用 allowed_state_variables 中一个变量；服务端覆盖 from/to 并在上下界及内部状态验证全部约束。不要使用近似坐标冒充严格关系，应从同一表达式构造依赖点。
优先采用简单构造：固定底边端点为常数，状态只驱动顶点或外点；中点/垂足用常数或共享表达式精确写出，使 midpoint/perpendicular 在整个采样范围恒成立。
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
        model_kind="scene",
        label="约束几何 IR",
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
            model_kind="ir_repair",
            label="约束几何 IR 修复",
        )
        try:
            ranking = rank_constraint_geometry_ir_candidates([parse_constraint_geometry_ir(repaired)], plan)
        except (TypeError, ValueError, json.JSONDecodeError):
            ranking = {"ok": False}
    if not ranking["ok"]:
        raise HtmlGenerationError(
            "约束几何 IR 未通过确定性校验，已停止生成",
            code="ir_generation_failed",
            detail="constraint_geometry_ir_invalid",
        )
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


def _invoke(prompt: str, schema: dict[str, Any], limit: int, *, model_kind: str, label: str) -> str:
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    return stream_ir_json(
        messages,
        response_schema=schema,
        max_chars=limit,
        model_kind=model_kind,
        label=label,
    ).text


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
    report = ranking.get("repair_report") if isinstance(ranking.get("repair_report"), dict) else {}
    return (
        "只修复报告中的确定性错误，保持对象身份和教学语义，输出完整单个 IR；不得放宽 tolerance。"
        "禁止引用未声明状态（如 B.x）；无效 drag 应删除或改为真正驱动坐标的绑定；"
        "未知对象约束应删除或改为已声明对象；coincident 只能引用两点。"
        + json.dumps(
            {
                "topic": topic,
                "variables": (plan.get("interactive_spec") or {}).get("variables", []),
                "candidate": repair_constraint_geometry_ir(ranking.get("repair_candidate"), plan),
                "errors": (report.get("errors") or [])[:12],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
