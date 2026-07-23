"""Plan contract helpers: compose TeachingPlan + GenerationSpec into a flat plan.

P0/P1 keep the public flat-plan API stable. Teaching and machine layers live in
``teaching_plan`` / ``machine_spec``; field ownership is declared in ``plan_layers``.
Later phases will expose Approach B wire ``{teaching_plan, generation_spec}``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from aetherviz_service.aetherviz.workflow.machine_spec import derive_generation_spec
from aetherviz_service.aetherviz.workflow.plan_diagnostics import (
    PlanDiagnostic,
    PlanNormalizationResult,
    check_plan_consistency,
)
from aetherviz_service.aetherviz.workflow.plan_layers import (
    GENERATION_SPEC_FIELDS,
    TEACHING_PLAN_FIELDS,
    extract_generation_spec,
    extract_teaching_plan,
    merge_plan_layers,
    split_plan_layers,
)
from aetherviz_service.aetherviz.workflow.plan_utils import DEFAULT_PRIMARY_COLOR
from aetherviz_service.aetherviz.workflow.teaching_plan import (
    REQUIRED_RUNTIME_CONTROLS,
    normalize_teaching_plan,
)

# Re-export for callers / tests that historically imported these symbols here.
__all__ = [
    "DEFAULT_PRIMARY_COLOR",
    "REQUIRED_RUNTIME_CONTROLS",
    "TEACHING_PLAN_FIELDS",
    "GENERATION_SPEC_FIELDS",
    "compact_plan_for_revision",
    "extract_generation_spec",
    "extract_teaching_plan",
    "merge_plan_layers",
    "normalize_plan",
    "normalize_plan_with_diagnostics",
    "parse_planning_result",
    "parse_planning_result_with_diagnostics",
    "split_plan_layers",
]


def compact_plan_for_revision(plan: dict[str, Any]) -> dict[str, Any]:
    """Compact teaching-layer fields for revise_plan prompts."""
    return {field: plan[field] for field in TEACHING_PLAN_FIELDS if field in plan}


def parse_planning_result(raw: str, topic: str = "", primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    return parse_planning_result_with_diagnostics(raw, topic, primary_color).plan


def parse_planning_result_with_diagnostics(
    raw: str,
    topic: str = "",
    primary_color: str = DEFAULT_PRIMARY_COLOR,
) -> PlanNormalizationResult:
    data: dict[str, Any] = {}
    if raw:
        cleaned = raw.strip()
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            raise
    return normalize_plan_with_diagnostics(data, topic, primary_color)


def normalize_plan(raw_plan: dict | None, topic: str, primary_color: str = DEFAULT_PRIMARY_COLOR) -> dict:
    return _normalize_plan(raw_plan, topic, primary_color, diagnostics=None)


def normalize_plan_with_diagnostics(
    raw_plan: dict | None,
    topic: str,
    primary_color: str = DEFAULT_PRIMARY_COLOR,
) -> PlanNormalizationResult:
    diagnostics: list[PlanDiagnostic] = []
    plan = _normalize_plan(raw_plan, topic, primary_color, diagnostics=diagnostics)
    diagnostics.extend(item for item in check_plan_consistency(plan) if item not in diagnostics)
    return PlanNormalizationResult(plan=plan, diagnostics=tuple(diagnostics))


def _normalize_plan(
    raw_plan: dict | None,
    topic: str,
    primary_color: str,
    *,
    diagnostics: list[PlanDiagnostic] | None,
) -> dict:
    """Compose teaching + generation layers into the legacy flat plan shape."""
    teaching = normalize_teaching_plan(raw_plan, topic, primary_color)
    generation = derive_generation_spec(teaching, raw_plan, diagnostics=diagnostics)
    return merge_plan_layers(teaching, generation)
