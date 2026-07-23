"""Two-layer plan ownership: TeachingPlan vs GenerationSpec.

TeachingPlan is user-facing and chat-editable. GenerationSpec is derived at
approve time for IR routing/generation and must not rewrite confirmed teaching
fields (interactive_spec numeric span narrowing is the only allowed machine
touch on teaching-owned interactive_spec bounds).
"""

from __future__ import annotations

from typing import Any

# User-readable teaching animation plan. Editable via plan / revise_plan.
TEACHING_PLAN_FIELDS: tuple[str, ...] = (
    "source_topic",
    "interactive_type",
    "title",
    "goal",
    "learner_level",
    "stage_layout",
    "key_points",
    "design_brief",
    "interactive_spec",
    "teaching_flow",
    "controls",
    "formulas",
    "primary_color",
)

# Machine IR routing / generation contract. Derived at approve; opaque to users.
GENERATION_SPEC_FIELDS: tuple[str, ...] = (
    "page_type",
    "widget_type",
    "subject",
    "knowledge_profile",
    "representation_spec",
    "recomposition_spec",
    "discipline_spec",
    "scene_outline",
    "widget_outline",
    "widget_actions",
    "runtime",
    "runtime_controls",
)

# Not owned by either teaching or generation content layers.
LIFECYCLE_FIELDS: tuple[str, ...] = (
    "status",
    "plan_id",
    "revision_summary",
    "context_status",
)

TEACHING_PLAN_FIELD_SET = frozenset(TEACHING_PLAN_FIELDS)
GENERATION_SPEC_FIELD_SET = frozenset(GENERATION_SPEC_FIELDS)
LIFECYCLE_FIELD_SET = frozenset(LIFECYCLE_FIELDS)


def merge_plan_layers(
    teaching_plan: dict[str, Any],
    generation_spec: dict[str, Any],
    *,
    lifecycle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose a flat legacy plan from explicit layers (Approach B wire helper).

    Flat ``controls`` always equals teaching learning-controls + generation
    runtime play/pause/reset. ``runtime_controls`` stays on the generation layer
    only and is not duplicated as the flat controls field.
    """
    from aetherviz_service.aetherviz.workflow.teaching_plan import (
        REQUIRED_RUNTIME_CONTROLS,
        learning_controls_only,
        with_runtime_controls,
    )

    teaching = dict(teaching_plan)
    generation = dict(generation_spec)
    teaching["controls"] = learning_controls_only(teaching.get("controls") if isinstance(teaching.get("controls"), list) else [])
    runtime_controls = generation.get("runtime_controls")
    if not isinstance(runtime_controls, list) or not runtime_controls:
        runtime_controls = [dict(control) for control in REQUIRED_RUNTIME_CONTROLS]
        generation["runtime_controls"] = runtime_controls
    merged = {**teaching, **generation}
    merged["controls"] = with_runtime_controls(teaching.get("controls"))
    # runtime_controls remains available on the flat plan for explicit dual-layer reads,
    # but downstream IR/layout continue to use merged ``controls``.
    if lifecycle:
        for field, value in lifecycle.items():
            if field in LIFECYCLE_FIELD_SET:
                merged[field] = value
    return merged


def extract_teaching_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Extract the teaching-layer subset from a flat (legacy) plan dict."""
    from aetherviz_service.aetherviz.workflow.teaching_plan import learning_controls_only

    result = {field: plan[field] for field in TEACHING_PLAN_FIELDS if field in plan}
    if "controls" in result and isinstance(result["controls"], list):
        result["controls"] = learning_controls_only(result["controls"])
    return result


def extract_generation_spec(plan: dict[str, Any]) -> dict[str, Any]:
    """Extract the generation-spec subset from a flat (legacy) plan dict."""
    from aetherviz_service.aetherviz.workflow.teaching_plan import REQUIRED_RUNTIME_CONTROLS

    result = {field: plan[field] for field in GENERATION_SPEC_FIELDS if field in plan}
    if "runtime_controls" not in result:
        # Legacy flat plans only had merged controls; recover runtime controls.
        result["runtime_controls"] = [dict(control) for control in REQUIRED_RUNTIME_CONTROLS]
    return result


def extract_lifecycle_fields(plan: dict[str, Any]) -> dict[str, Any]:
    return {field: plan[field] for field in LIFECYCLE_FIELDS if field in plan}


def split_plan_layers(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Split a flat plan into (teaching_plan, generation_spec, lifecycle)."""
    return (
        extract_teaching_plan(plan),
        extract_generation_spec(plan),
        extract_lifecycle_fields(plan),
    )
