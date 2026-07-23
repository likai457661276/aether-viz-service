"""Compile a confirmed TeachingPlan into a GenerationSpec.

Approve-time path: deterministic derive first, then one bounded LLM enhancement of
representation_spec / recomposition_spec when the deterministic route is weak.
Teaching fields are never rewritten (except allowed interactive_spec span narrowing
inside derive_generation_spec).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_text,
    has_planning_llm_config,
)
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY, IRBackendRegistry
from aetherviz_service.aetherviz.ir.router.capability_catalog import build_ir_capability_catalog
from aetherviz_service.aetherviz.ir.router.contracts import IRRouteDecision
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.machine_spec import derive_generation_spec
from aetherviz_service.aetherviz.workflow.plan_diagnostics import (
    PlanDiagnostic,
    check_plan_consistency,
    has_consistency_errors,
)
from aetherviz_service.aetherviz.workflow.plan_layers import (
    extract_generation_spec,
    extract_lifecycle_fields,
    extract_teaching_plan,
    merge_plan_layers,
)
from aetherviz_service.aetherviz.workflow.plan_utils import DEFAULT_PRIMARY_COLOR, normalize_primary_color, safe_str
from aetherviz_service.aetherviz.workflow.teaching_plan import normalize_teaching_plan
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

_COMPILE_SYSTEM_PROMPT = """你是互动教学课件的机器规格编译器。
只输出一个合法 JSON 对象，不输出 Markdown 或解释。
JSON 顶层字段只能包含 representation_spec，以及在教学语义确实需要切分重排时可选的 recomposition_spec。
representation_spec 是服务端选择实现的权威能力配置：描述通用视觉能力，不直接填写实现后端名称。
字段约束：version 固定 1.0；views / state_variables / correspondences / required_invariants / interaction_requirements 使用既定枚举。
views.kind 只能是 coordinate_plane、geometric_scene、number_line、data_chart、probability_experiment、probability_tree、discrete_structure、graph、tree、set_diagram、sequence、process_diagram、symbolic_panel、object_scene；
state_variables.semantic_type 只能是 scalar、angle、length、time、ratio、vector、discrete；
correspondences.type 只能是 shared_parameter、point_on_curve、projection、equal_value、coincident、transform、decompose_recompose、derived_value；
required_invariants 只使用 point_on_curve、equal_value、coincident、piece_identity_preserved、piece_count_constant、area_preserved、length_preserved、angle_preserved、piece_congruence、collinear、parallel、perpendicular、equal_length、midpoint、point_on_circle、tangent、equal_angle、supplementary、probability_mass、stable_identity、acyclic、set_membership；
interaction_requirements 只使用 scrub、play、pause、reset、preset、drag、reveal、trace。
recomposition_spec 仅在稳定拼片切分重排时输出，只含 topology_variables、geometry_variables、invariants、proof_constraints。

{capability_catalog}

根据教学计划和路由反馈编译机器规格，使计划落入已验证能力范围；不得改写教学语义字段。
"""


@dataclass(frozen=True)
class PlanCompileResult:
    teaching_plan: dict[str, Any]
    generation_spec: dict[str, Any]
    plan: dict[str, Any]
    diagnostics: tuple[PlanDiagnostic, ...]
    metrics: dict[str, Any]


def compile_plan_layers(
    *,
    topic: str,
    teaching_plan: dict[str, Any] | None = None,
    generation_spec: dict[str, Any] | None = None,
    flat_plan: dict[str, Any] | None = None,
    primary_color: str = DEFAULT_PRIMARY_COLOR,
    registry: IRBackendRegistry = DEFAULT_IR_REGISTRY,
    allow_llm: bool = True,
) -> PlanCompileResult:
    """Normalize teaching, derive/enhance generation spec, return dual + flat plan."""
    raw_flat = dict(flat_plan) if isinstance(flat_plan, dict) else {}
    color = normalize_primary_color(
        (teaching_plan or raw_flat).get("primary_color") if isinstance(teaching_plan or raw_flat, dict) else primary_color,
        primary_color,
    )
    source_topic = (
        safe_str((teaching_plan or {}).get("source_topic"))
        or safe_str(raw_flat.get("source_topic"))
        or safe_str(raw_flat.get("topic"))
        or topic
    )

    teaching_source = dict(teaching_plan) if isinstance(teaching_plan, dict) else extract_teaching_plan(raw_flat)
    if not teaching_source and raw_flat:
        teaching_source = extract_teaching_plan(raw_flat)
    if "source_topic" not in teaching_source:
        teaching_source["source_topic"] = source_topic

    teaching = normalize_teaching_plan(teaching_source, source_topic, color)
    lifecycle = extract_lifecycle_fields(raw_flat)
    if isinstance(teaching_plan, dict):
        lifecycle = {**lifecycle, **extract_lifecycle_fields(teaching_plan)}

    # Hints from an explicit generation_spec or legacy flat machine fields.
    raw_hints = dict(raw_flat)
    if isinstance(generation_spec, dict) and generation_spec:
        raw_hints.update(generation_spec)

    diagnostics: list[PlanDiagnostic] = []
    teaching_for_derive = dict(teaching)
    baseline_generation = derive_generation_spec(teaching_for_derive, raw_hints, diagnostics=diagnostics)
    # derive may narrow interactive_spec spans on teaching_for_derive.
    teaching = teaching_for_derive

    baseline_plan = merge_plan_layers(teaching, baseline_generation, lifecycle=lifecycle or None)
    preview = resolve_generation_route(baseline_plan, registry=registry, allow_llm=False)

    metrics: dict[str, Any] = {
        "plan_compile_attempted": True,
        "plan_compile_llm_attempted": False,
        "plan_compile_llm_accepted": False,
        "plan_compile_selected_backend": preview.selected_backend,
        "plan_compile_confidence": preview.confidence,
        "plan_compile_reasons": list(preview.reasons)[:8],
        "route_preview_selected_backend": preview.selected_backend,
        "route_preview_confidence": preview.confidence,
        "route_preview_reasons": list(preview.reasons)[:8],
    }

    final_plan = baseline_plan
    final_diagnostics = tuple(diagnostics)

    if allow_llm and _needs_compile_enhancement(preview) and has_planning_llm_config():
        metrics["plan_compile_llm_attempted"] = True
        try:
            enhanced_fields = _llm_compile_representation_fields(
                teaching,
                baseline_generation,
                topic=source_topic,
                feedback=_format_route_feedback(preview),
            )
        except Exception as exc:
            logger.warning("plan compile LLM enhancement failed: %s", exc)
            metrics["plan_compile_skipped"] = type(exc).__name__
        else:
            enhanced_hints = dict(raw_hints)
            enhanced_hints.update(enhanced_fields)
            enhanced_diagnostics: list[PlanDiagnostic] = []
            enhanced_teaching = dict(teaching)
            enhanced_generation = derive_generation_spec(
                enhanced_teaching,
                enhanced_hints,
                diagnostics=enhanced_diagnostics,
            )
            enhanced_plan = merge_plan_layers(enhanced_teaching, enhanced_generation, lifecycle=lifecycle or None)
            post = resolve_generation_route(enhanced_plan, registry=registry, allow_llm=False)
            reject = _enhancement_rejection_reason(preview, post, enhanced_diagnostics)
            metrics["plan_compile_post_selected_backend"] = post.selected_backend
            metrics["plan_compile_post_confidence"] = post.confidence
            if reject is None:
                final_plan = enhanced_plan
                final_diagnostics = tuple(enhanced_diagnostics)
                metrics["plan_compile_llm_accepted"] = True
                metrics["plan_compile_selected_backend"] = post.selected_backend
                metrics["plan_compile_confidence"] = post.confidence
                metrics["plan_compile_reasons"] = list(post.reasons)[:8]
                metrics["route_preview_selected_backend"] = post.selected_backend
                metrics["route_preview_confidence"] = post.confidence
                metrics["route_preview_reasons"] = list(post.reasons)[:8]
            else:
                metrics["plan_compile_llm_rejected_reason"] = reject

    consistency = check_plan_consistency(final_plan)
    merged_diagnostics = tuple(dict.fromkeys((*final_diagnostics, *consistency)))
    metrics["plan_diagnostics"] = [item.as_dict() for item in merged_diagnostics]
    return PlanCompileResult(
        teaching_plan=extract_teaching_plan(final_plan),
        generation_spec=extract_generation_spec(final_plan),
        plan=final_plan,
        diagnostics=merged_diagnostics,
        metrics=metrics,
    )


def resolve_wire_layers(
    *,
    flat_plan: dict[str, Any] | None = None,
    teaching_plan: dict[str, Any] | None = None,
    generation_spec: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    """Normalize Approach B dual objects or legacy flat plan into layer dicts."""
    flat = dict(flat_plan) if isinstance(flat_plan, dict) else {}
    teaching = dict(teaching_plan) if isinstance(teaching_plan, dict) else None
    generation = dict(generation_spec) if isinstance(generation_spec, dict) else None
    lifecycle = extract_lifecycle_fields(flat)
    if teaching is None and flat:
        teaching = extract_teaching_plan(flat)
        lifecycle = {**lifecycle, **extract_lifecycle_fields(flat)}
    if generation is None and flat and any(field in flat for field in ("representation_spec", "runtime", "subject")):
        generation = extract_generation_spec(flat)
    if isinstance(teaching_plan, dict):
        lifecycle = {**lifecycle, **extract_lifecycle_fields(teaching_plan)}
    return teaching, generation, lifecycle


def _needs_compile_enhancement(route: IRRouteDecision) -> bool:
    if route.selected_backend is None:
        return True
    return route.confidence < settings.aetherviz_ir_router_deterministic_threshold


def _enhancement_rejection_reason(
    before: IRRouteDecision,
    after: IRRouteDecision,
    diagnostics: list[PlanDiagnostic] | tuple[PlanDiagnostic, ...],
) -> str | None:
    if has_consistency_errors(tuple(diagnostics)):
        return "post_compile_plan_inconsistent"
    if after.selected_backend is None:
        return "post_compile_still_unroutable"
    if before.selected_backend is not None and after.confidence + 1e-9 < before.confidence:
        return "post_compile_confidence_decreased"
    return None


def _format_route_feedback(route: IRRouteDecision) -> str:
    lines: list[str] = []
    if route.selected_backend is None:
        lines.append("当前草稿没有合格的可视化能力后端（selected_backend=None）。")
    else:
        lines.append(
            f"当前草稿路由置信度偏低：confidence={route.confidence:.3f}，"
            f"低于确定性阈值 {settings.aetherviz_ir_router_deterministic_threshold:.2f}。"
        )
    for candidate in route.candidates[:6]:
        missing = "、".join(candidate.missing_capabilities) or "无"
        exclusions = "；".join(candidate.exclusion_reasons) or "无"
        lines.append(
            f"- 候选能力族 score={candidate.score:.3f} eligible={candidate.eligible}；"
            f"缺失能力：{missing}；排除原因：{exclusions}"
        )
    if route.reasons:
        lines.append("路由理由：" + "；".join(str(item) for item in route.reasons[:6]))
    return "\n".join(lines)


def _llm_compile_representation_fields(
    teaching: dict[str, Any],
    generation: dict[str, Any],
    *,
    topic: str,
    feedback: str,
) -> dict[str, Any]:
    system_prompt = _COMPILE_SYSTEM_PROMPT.format(capability_catalog=build_ir_capability_catalog())
    compact = {
        "title": teaching.get("title"),
        "goal": teaching.get("goal"),
        "interactive_type": teaching.get("interactive_type"),
        "interactive_spec": teaching.get("interactive_spec"),
        "teaching_flow": teaching.get("teaching_flow"),
        "design_brief": teaching.get("design_brief"),
        "key_points": teaching.get("key_points"),
        "formulas": teaching.get("formulas"),
        "representation_spec": generation.get("representation_spec"),
        "recomposition_spec": generation.get("recomposition_spec"),
        "discipline_spec": generation.get("discipline_spec"),
    }
    user_prompt = (
        f"主题：{topic}\n"
        f"路由预览反馈：\n{feedback}\n\n"
        f"已确认教学计划与当前确定性机器规格草稿：\n"
        f"{json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}\n"
    )
    model = create_chat_model("plan_compile")
    response = model.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    raw = extract_llm_text(response).strip()
    if not raw:
        raise ValueError("empty_plan_compile")
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("plan_compile_not_json")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("plan_compile_not_object")
    result: dict[str, Any] = {}
    if isinstance(parsed.get("representation_spec"), dict):
        result["representation_spec"] = parsed["representation_spec"]
    if isinstance(parsed.get("recomposition_spec"), dict):
        result["recomposition_spec"] = parsed["recomposition_spec"]
    if "representation_spec" not in result:
        raise ValueError("plan_compile_missing_representation_spec")
    return result
