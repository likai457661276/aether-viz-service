"""Model-to-IR generation for linked coordinate scenes."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.html_agent import (
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_text,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.ir.linked_coordinate.contract import (
    LINKED_COORDINATE_IR_MAX_CHARS,
    LINKED_COORDINATE_IR_VERSION,
    linked_coordinate_ir_candidates_response_schema,
    linked_coordinate_ir_response_schema,
    parse_linked_coordinate_ir,
    parse_linked_coordinate_ir_candidates,
    rank_linked_coordinate_ir_candidates,
)
from aetherviz_service.aetherviz.ir.linked_coordinate.runtime import (
    assemble_linked_coordinate_business_html,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

LINKED_COORDINATE_SYSTEM_PROMPT = f"""你是动态数学场景的结构化联动坐标 IR 生成器。
只输出一个 JSON 对象，不输出 HTML、JavaScript、Markdown、注释或解释。version 固定为 {LINKED_COORDINATE_IR_VERSION}。

目标是让多个坐标系、函数曲线、轨迹、动态点和投影连线共享同一数学状态，服务端负责 SVG、响应式布局和动画生命周期。不得在不同对象中手写互相矛盾的正负号或缩放逻辑。

IR 顶层字段固定为 version、definitions、animation、coordinate_systems、curves、points、links、invariants：
- definitions：0~32 个命名表达式。
- animation：variable 必须是 allowed_state_variables 中一个可调变量；from/to 是其有效边界，duration 取 2~8 秒。
- coordinate_systems：1~4 个坐标系，画布固定 960×560；x/y/width/height 是屏幕布局数值，宽高至少 120 且不得越界；x_domain/y_domain 是数学坐标范围。
- curves：1~8 条完整曲线；parameter 是仅在本曲线采样时有效的局部变量，samples 为 48~160；x/y 都是数学坐标表达式。
- points：1~16 个动态数学点；x/y 使用与对应曲线相同的定义和符号约定。
- links：只连接已声明 point id，用于跨表征投影或对应关系。
- invariants：至少 1 项，必须覆盖每个关键动态对应关系。type 只允许 point_on_curve、equal_value、coincident。

表达式仅允许：数值；{{"state":"计划变量"}}；{{"var":"definition"}}；曲线内 {{"local":"参数名"}}；或 {{"op":"操作符","args":[...]}}。definitions、坐标域、动态点、动画和不变量只能使用状态表达式，禁止引用 local；local 只允许出现在所属曲线的 x/y 中，依赖局部参数的函数应内联到曲线表达式。操作符仅允许 add,sub,mul,div,pow,mod,min,max,clamp,neg,abs,sqrt,sin,cos,tan,asin,acos,atan,atan2,exp,log,deg_to_rad。三角函数内部统一使用弧度；计划角度变量 unit 为 degree、deg、° 或度时，传入 sin/cos/tan 前必须显式使用 deg_to_rad。

不变量左右操作数结构固定为 {{"kind":"point|curve_sample|value","ref":"id或空字符串","at":表达式,"axis":"x|y|both","value":表达式}}：
- point_on_curve：left 使用动态 point，right 使用 curve_sample，right.at 必须是产生该点的同一参数；axis=both。
- equal_value：两侧可使用 point/curve_sample 的 x 或 y，也可用 value；用于证明跨坐标系共享数值。
- coincident：比较同一数学坐标系中的点或曲线采样；axis=both。
未使用的 ref 填空字符串、at/value 填 0，以满足固定 Schema。

输出前必须在计划变量 minimum/default/maximum 三组状态下逐项代入：坐标域严格递增、所有结果有限、每个 point_on_curve/equal_value/coincident 的误差不超过 tolerance。尤其检查 SVG 屏幕 y 轴翻转只由服务端坐标变换处理，IR 中始终写数学 y 值，禁止为了屏幕坐标额外取负。
不得针对单位圆、正弦波或其他单个知识点使用专用字段或模板；只组合上述通用坐标系、曲线、点、连线和可计算不变量。IR 不超过 {LINKED_COORDINATE_IR_MAX_CHARS} 字符。"""


def stream_generate_linked_coordinate_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    runner = (
        _traced_stream_generate_linked_coordinate_html
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_generate_linked_coordinate_html_impl
    )
    yield from runner(topic, plan)


@traceable(
    name="aetherviz.linked_coordinate_ir_generation",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "linked_coordinate_ir_generation"},
    process_inputs=lambda inputs: {
        "topic": inputs.get("topic"),
        "representation_type": ((inputs.get("plan") or {}).get("knowledge_profile") or {}).get(
            "representation_type"
        ),
    },
    reduce_fn=lambda items: {
        "completed": any(isinstance(item, HtmlStreamResult) for item in items),
        "degraded": any(isinstance(item, HtmlStreamResult) and item.degraded for item in items),
    },
)
def _traced_stream_generate_linked_coordinate_html(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_generate_linked_coordinate_html_impl(topic, plan)


def _stream_generate_linked_coordinate_html_impl(
    topic: str, plan: dict[str, Any]
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError(
            "联动坐标 IR 生成失败，未配置可用的模型服务",
            code="model_unavailable",
            detail="OPENAI_API_KEY is not configured",
        )
    yield build_html_progress_payload(
        [
            {"content": "生成联动坐标 IR", "status": "in_progress"},
            {"content": "验证数学不变量", "status": "pending"},
            {"content": "编译服务端响应式运行时", "status": "pending"},
        ]
    )
    raw = _stream_ir(
        _build_prompt(topic, plan),
        linked_coordinate_ir_candidates_response_schema(),
        max_chars=LINKED_COORDINATE_IR_MAX_CHARS * 2 + 2_048,
    )
    degraded = False
    try:
        candidates = parse_linked_coordinate_ir_candidates(raw)
        ranking = rank_linked_coordinate_ir_candidates(candidates, plan)
    except ValueError as exc:
        candidates = []
        ranking = {
            "ok": False,
            "repair_candidate": raw,
            "candidates": [{"report": _parse_report(str(exc))}],
        }
    if ranking["ok"]:
        ir = ranking["selected_ir"]
    else:
        degraded = True
        repair_candidate = ranking.get("repair_candidate")
        repair_report = _ranking_report(ranking)
        repair_prompt = _build_repair_prompt(topic, plan, repair_candidate, repair_report)
        repaired = _stream_ir(
            repair_prompt,
            linked_coordinate_ir_response_schema(),
            max_chars=LINKED_COORDINATE_IR_MAX_CHARS + 1_024,
        )
        try:
            ir = parse_linked_coordinate_ir(repaired)
            repaired_ranking = rank_linked_coordinate_ir_candidates([ir], plan)
        except ValueError as exc:
            repaired_ranking = {"ok": False, "candidates": [{"report": _parse_report(str(exc))}]}
        if not repaired_ranking["ok"]:
            final_report = _ranking_report(repaired_ranking)
            raise HtmlGenerationError(
                "联动坐标 IR 未通过确定性数学检查",
                code="linked_coordinate_ir_invalid",
                detail=json.dumps(final_report.get("errors", [])[:8], ensure_ascii=False),
            )
    yield build_html_progress_payload(
        [
            {"content": "生成联动坐标 IR", "status": "completed"},
            {"content": "验证数学不变量", "status": "completed"},
            {"content": "编译服务端响应式运行时", "status": "completed"},
        ]
    )
    yield HtmlStreamResult(
        html=assemble_linked_coordinate_business_html(ir, plan, topic),
        degraded=degraded,
        truncated=False,
        strategy="linked_coordinate_ir",
        source_chars=len(raw),
        output_chars=len(raw),
    )


def _stream_ir(prompt: str, response_schema: dict[str, Any], *, max_chars: int) -> str:
    messages = [SystemMessage(content=LINKED_COORDINATE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    raw = ""
    try:
        model = create_chat_model("scene", response_schema=response_schema)
        for chunk in model.stream(messages):
            raw += extract_llm_text(chunk)
            if len(raw) > max_chars:
                break
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("strict linked coordinate IR schema unavailable; using JSON mode: %s", exc)
        raw = ""
        for chunk in create_chat_model("scene").stream(messages):
            raw += extract_llm_text(chunk)
            if len(raw) > max_chars:
                break
    return raw


def _build_prompt(topic: str, plan: dict[str, Any]) -> str:
    compact = {
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
        "根据已确认计划一次生成两个相互独立的通用联动坐标 IR 候选。顶层严格输出 "
        "{\"candidates\":[IR1,IR2]}。每个候选先选择共享动画参数和数学定义，再布置坐标系，"
        "最后让完整曲线、动态点和投影连线全部引用同一表达式，并用可计算不变量证明对应关系。"
        "不得输出 HTML 或 JavaScript。\n"
        + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    )


def _build_repair_prompt(
    topic: str, plan: dict[str, Any], candidate: object, report: dict[str, Any]
) -> str:
    return (
        "只修复下列联动坐标 IR 的确定性错误，输出完整单个 JSON 对象。保留教学意图和通用结构；"
        "统一数学坐标符号，修正曲线、动态点和不变量的同源表达式；严格遵守错误字段所处作用域，"
        "definitions 不得引用 local，依赖局部参数的函数直接内联到对应 curve.x/curve.y；"
        "角度制进入 sin/cos/tan 前使用 deg_to_rad；不要通过放宽 tolerance 掩盖错误。\n"
        + json.dumps(
            {
                "topic": topic,
                "allowed_state_variables": _variables(plan),
                "errors": report.get("errors", []),
                "candidate": candidate,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _variables(plan: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    return [
        {
            key: item.get(key)
            for key in ("name", "label", "min", "max", "default", "step", "unit")
        }
        for item in spec.get("variables", [])
        if isinstance(item, dict) and not item.get("computed") and item.get("name")
    ]


def _parse_report(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "severity": "error",
        "summary": "联动坐标 IR 解析失败",
        "errors": [{"type": "linked_coordinate_ir_parse", "message": message}],
        "warnings": [],
    }


def _ranking_report(ranking: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for candidate in ranking.get("candidates", []):
        report = candidate.get("report") if isinstance(candidate, dict) else None
        if isinstance(report, dict):
            errors.extend(item for item in report.get("errors", []) if isinstance(item, dict))
    return {
        "ok": False,
        "severity": "error",
        "summary": "所有联动坐标 IR 候选均未通过确定性检查",
        "errors": errors,
        "warnings": [],
    }
