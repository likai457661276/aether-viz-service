"""Model-to-IR generation for stable single-view coordinate graphs."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.model_factory import has_primary_llm_config
from aetherviz_service.aetherviz.contracts.html_stream import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.ir.coordinate_graph.contract import (
    COORDINATE_GRAPH_IR_MAX_CHARS,
    COORDINATE_GRAPH_IR_VERSION,
    coordinate_graph_ir_candidates_response_schema,
    coordinate_graph_ir_response_schema,
    parse_coordinate_graph_ir,
    parse_coordinate_graph_ir_candidates,
    rank_coordinate_graph_ir_candidates,
)
from aetherviz_service.aetherviz.ir.coordinate_graph.runtime import (
    assemble_coordinate_graph_business_html,
)
from aetherviz_service.aetherviz.ir.stream import stream_ir_json
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

COORDINATE_GRAPH_SYSTEM_PROMPT = f"""你是单视图数学坐标图 IR 生成器。
只输出 JSON，不输出 HTML、JavaScript、CSS、Markdown 或解释。version 固定为 {COORDINATE_GRAPH_IR_VERSION}。

服务端统一负责 960×560 像素对齐 SVG、坐标映射、屏幕 y 轴翻转、响应式布局、描边、字号和动画生命周期。IR 只表达数学语义，禁止输出 SVG 坐标、transform、viewBox、像素字号、描边宽度或任意脚本。

顶层字段固定为 version、definitions、animation、coordinate_systems、curves、points、links、invariants：
- coordinate_systems 必须且只能有 1 个，只输出 id、x_domain、y_domain、label；数学域在所有可调变量边界均须严格递增且有限。
- curves 描述完整数学曲线，x/y 使用表达式树；parameter 是曲线局部变量，parameter_unit 为 radian、degree 或 scalar；domain 必须稳定，动态揭示用 reveal。
- points 描述数学点。关键曲线至少配置一个动态点，并通过 point_on_curve 不变量证明点始终位于曲线上。
- links 仅用于同一坐标系内确有教学意义的投影或辅助线，否则输出空数组。
- animation.variable 必须来自 allowed_state_variables；from/to 位于变量范围内，duration 为 2~8 秒。存在两个或更多可调变量时必须输出 keyframes，每项为 {{"progress":0~1,"state":{{"变量":数值}}}}，首尾 progress 为 0 和 1、严格递增，并在每一帧覆盖全部可调变量；单变量可省略 keyframes。
- invariants 至少包含 point_on_curve；equal_value 或 coincident 仅在数学关系确实成立时使用，tolerance 不超过 0.001。

表达式仅允许数值；{{"state":"计划变量"}}；{{"var":"definition"}}；曲线内 {{"local":"局部参数"}}；或 {{"op":"操作符","args":[...]}}。操作符仅允许 add,sub,mul,div,pow,mod,min,max,clamp,neg,abs,sqrt,sin,cos,tan,asin,acos,atan,atan2,exp,log,deg_to_rad。角度为 degree、deg、° 或度时，进入三角函数前必须使用 deg_to_rad。

不变量操作数固定为 {{"kind":"point|curve_sample|value","ref":"id或空字符串","at":表达式,"axis":"x|y|both","value":表达式}}。point_on_curve 的动态点和曲线采样必须使用同源表达式；不要用宽松 tolerance 掩盖符号或参数错误。

所有学生可见说明使用简体中文；数学符号可保留。不得为某个具体函数增加专用字段或模板。输出前在全部变量 minimum/default/maximum 状态代入检查有限性、定义域和不变量。IR 不超过 {COORDINATE_GRAPH_IR_MAX_CHARS} 字符。"""


def stream_generate_coordinate_graph_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    runner = (
        _traced_stream_generate_coordinate_graph_html
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_generate_coordinate_graph_html_impl
    )
    yield from runner(topic, plan)


@traceable(
    name="aetherviz.coordinate_graph_ir_generation",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "coordinate_graph_ir_generation"},
    process_inputs=lambda inputs: {
        "topic": inputs.get("topic"),
        "representation_type": ((inputs.get("plan") or {}).get("knowledge_profile") or {}).get("representation_type"),
    },
    reduce_fn=lambda items: {"completed": any(isinstance(item, HtmlStreamResult) for item in items)},
)
def _traced_stream_generate_coordinate_graph_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_generate_coordinate_graph_html_impl(topic, plan)


def _stream_generate_coordinate_graph_html_impl(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError(
            "坐标图 IR 生成失败，未配置可用的模型服务",
            code="model_unavailable",
            detail="OPENAI_API_KEY is not configured",
        )
    yield build_html_progress_payload(
        [
            {"content": "生成单视图坐标 IR", "status": "in_progress"},
            {"content": "验证函数与动态点不变量", "status": "pending"},
            {"content": "编译服务端坐标运行时", "status": "pending"},
        ]
    )
    raw = _stream_ir(
        _build_prompt(topic, plan),
        coordinate_graph_ir_candidates_response_schema(),
        COORDINATE_GRAPH_IR_MAX_CHARS * 3 + 2_048,
        label="坐标图 IR",
    )
    degraded = False
    try:
        candidates = parse_coordinate_graph_ir_candidates(raw)
        ranking = rank_coordinate_graph_ir_candidates(candidates, plan)
    except ValueError as exc:
        ranking = {"ok": False, "repair_candidate": raw, "repair_report": _parse_report(str(exc))}
    if ranking["ok"]:
        ir = ranking["selected_ir"]
    else:
        degraded = True
        repaired = _stream_ir(
            _build_repair_prompt(topic, plan, ranking.get("repair_candidate"), ranking.get("repair_report") or {}),
            coordinate_graph_ir_response_schema(),
            COORDINATE_GRAPH_IR_MAX_CHARS + 1_024,
            label="坐标图 IR 修复",
        )
        try:
            candidate = parse_coordinate_graph_ir(repaired)
            repaired_ranking = rank_coordinate_graph_ir_candidates([candidate], plan)
        except ValueError as exc:
            repaired_ranking = {"ok": False, "repair_report": _parse_report(str(exc))}
        if not repaired_ranking["ok"]:
            report = repaired_ranking.get("repair_report") or {}
            logger.warning(
                "coordinate graph IR failed deterministic validation: %s",
                json.dumps(report.get("errors", [])[:8], ensure_ascii=False),
            )
            raise HtmlGenerationError(
                "坐标图 IR 未通过确定性校验，已停止生成",
                code="ir_generation_failed",
                detail="coordinate_graph_ir_invalid",
            )
        ir = repaired_ranking["selected_ir"]
    yield build_html_progress_payload(
        [
            {"content": "生成单视图坐标 IR", "status": "completed"},
            {"content": "验证函数与动态点不变量", "status": "completed"},
            {"content": "编译服务端坐标运行时", "status": "completed"},
        ]
    )
    html = assemble_coordinate_graph_business_html(ir, plan, topic)
    yield HtmlStreamResult(
        html=html,
        degraded=degraded,
        truncated=False,
        strategy="coordinate_graph_ir",
        source_chars=len(raw),
        output_chars=len(raw),
    )


def _stream_ir(prompt: str, schema: dict[str, Any], max_chars: int, *, label: str) -> str:
    messages = [SystemMessage(content=COORDINATE_GRAPH_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    return stream_ir_json(
        messages,
        response_schema=schema,
        max_chars=max_chars,
        label=label,
    ).text


def _build_prompt(topic: str, plan: dict[str, Any]) -> str:
    payload = {
        "topic": topic,
        "goal": plan.get("goal"),
        "allowed_state_variables": _variables(plan),
        "knowledge_profile": plan.get("knowledge_profile"),
        "discipline_spec": plan.get("discipline_spec"),
        "teaching_flow": plan.get("teaching_flow"),
        "formulas": plan.get("formulas"),
        "representation_spec": plan.get("representation_spec"),
        "design_brief": plan.get("design_brief"),
    }
    return (
        '一次生成 3 个独立候选，严格输出 {"candidates":[IR1,IR2,IR3]}，不得少于 2 个。'
        "每个候选都只使用一个坐标系，让曲线、动态点和不变量引用同一组定义；"
        "候选之间使用不同但通用的数学组织方式。\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _build_repair_prompt(topic: str, plan: dict[str, Any], candidate: object, report: dict[str, Any]) -> str:
    return (
        "只修复确定性错误并输出完整单个 JSON 对象。必须保留一个 coordinate_system；统一曲线与动态点的同源表达式；"
        "补齐严格成立的 point_on_curve；修正域、单位、有限性或引用错误；不要放宽 tolerance。\n"
        + json.dumps(
            {
                "topic": topic,
                "allowed_state_variables": _variables(plan),
                "errors": (report.get("errors") or [])[:12],
                "candidate": candidate,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _variables(plan: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    return [
        {key: item.get(key) for key in ("name", "label", "min", "max", "default", "step", "unit")}
        for item in spec.get("variables", [])
        if isinstance(item, dict) and not item.get("computed") and item.get("name")
    ]


def _parse_report(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "errors": [{"type": "coordinate_graph_ir_parse", "message": message}],
        "warnings": [],
    }
