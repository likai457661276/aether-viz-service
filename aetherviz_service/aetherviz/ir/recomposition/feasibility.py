"""Plan-level feasibility checks that run before recomposition model generation."""

from __future__ import annotations

import math
from typing import Any

from aetherviz_service.aetherviz.ir.recomposition.contract import MAX_EXPANDED_PIECES

_SUPPORTED_MEASURE_INVARIANTS = {
    "area_preserved",
    "length_preserved",
    "angle_preserved",
    "piece_congruence",
}
_SUPPORTED_RELATIONS = {
    "equal_area",
    "equal_length",
    "equal_angle",
    "parallel",
    "perpendicular",
    "coincident",
    "collinear",
    "congruent",
}
_SUPPORTED_ASSEMBLIES = {"connected", "non_overlapping", "approximate_rectangle"}


def evaluate_recomposition_plan_feasibility(plan: dict[str, Any]) -> dict[str, Any]:
    """Reject plans whose declared bounded state space cannot fit the IR contract."""
    errors: list[dict[str, Any]] = []
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    proof = spec.get("proof_constraints") if isinstance(spec.get("proof_constraints"), dict) else {}
    variables = {
        str(item.get("name")): item
        for item in ((plan.get("interactive_spec") or {}).get("variables") or [])
        if isinstance(item, dict) and str(item.get("name") or "")
    }

    topology_product = 1
    topology_variables = [str(name) for name in spec.get("topology_variables", []) if str(name)]
    for name in topology_variables:
        variable = variables.get(name)
        if variable is None:
            errors.append(_issue("missing_topology_variable", variable=name))
            continue
        bounds = _bounded_discrete_range(variable)
        if bounds is None:
            errors.append(_issue("invalid_topology_range", variable=name))
            continue
        minimum, maximum = bounds
        if minimum < 1:
            errors.append(_issue("non_positive_topology_range", variable=name, minimum=minimum))
        topology_product *= max(1, maximum)
    if topology_product > MAX_EXPANDED_PIECES:
        errors.append(
            _issue(
                "expanded_piece_budget_exceeded",
                maximum_expanded_pieces=topology_product,
                supported_maximum=MAX_EXPANDED_PIECES,
            )
        )

    stages = [item for item in proof.get("stage_requirements", []) if isinstance(item, dict)]
    if not 3 <= len(stages) <= 5:
        errors.append(_issue("unsupported_stage_count", count=len(stages), supported=[3, 5]))

    measures = {str(item) for item in proof.get("measure_invariants", [])}
    unsupported_measures = sorted(measures - _SUPPORTED_MEASURE_INVARIANTS)
    if unsupported_measures:
        errors.append(_issue("unsupported_measure_invariant", values=unsupported_measures))

    relations = {
        str(item.get("type") or "")
        for item in proof.get("target_relations", [])
        if isinstance(item, dict)
    }
    unsupported_relations = sorted(relations - _SUPPORTED_RELATIONS)
    if unsupported_relations:
        errors.append(_issue("unsupported_target_relation", values=unsupported_relations))

    assemblies = {
        str(item.get("type") or "")
        for item in proof.get("target_assembly", [])
        if isinstance(item, dict)
    }
    unsupported_assemblies = sorted(assemblies - _SUPPORTED_ASSEMBLIES)
    if unsupported_assemblies:
        errors.append(_issue("unsupported_target_assembly", values=unsupported_assemblies))

    return {
        "ok": not errors,
        "errors": errors,
        "topology_variables": topology_variables,
        "maximum_expanded_pieces": topology_product,
        "supported_maximum_expanded_pieces": MAX_EXPANDED_PIECES,
    }


def format_recomposition_feasibility_errors(report: dict[str, Any]) -> str:
    reasons: list[str] = []
    for error in report.get("errors", []):
        if not isinstance(error, dict):
            continue
        error_type = str(error.get("type") or "recomposition_plan_infeasible")
        if error_type == "expanded_piece_budget_exceeded":
            reasons.append(
                f"计划最大展开图元数 {error.get('maximum_expanded_pieces')} 超过 IR 上限 "
                f"{error.get('supported_maximum')}"
            )
        elif error.get("variable"):
            reasons.append(f"{error_type}:{error['variable']}")
        else:
            reasons.append(error_type)
    return "；".join(reasons) or "recomposition_plan_infeasible"


def _bounded_discrete_range(variable: dict[str, Any]) -> tuple[int, int] | None:
    try:
        minimum = float(variable.get("min"))
        maximum = float(variable.get("max"))
        step = float(variable.get("step"))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (minimum, maximum, step)):
        return None
    if minimum > maximum or step < 1 or not all(item.is_integer() for item in (minimum, maximum, step)):
        return None
    return int(minimum), int(maximum)


def _issue(issue_type: str, **details: Any) -> dict[str, Any]:
    return {"type": issue_type, **details}
