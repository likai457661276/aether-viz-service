"""Local targets for deterministic constraint-geometry IR repair regression."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.constraint_geometry.contract import (
    rank_constraint_geometry_ir_candidates,
    repair_constraint_geometry_ir,
    validate_constraint_geometry_ir,
)
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def run_constraint_geometry_ir_case(inputs: dict[str, Any]) -> dict[str, Any]:
    topic = str(inputs.get("case_id") or "constraint-geometry")
    plan = normalize_plan(inputs.get("plan") if isinstance(inputs.get("plan"), dict) else {}, topic)
    mode = str(inputs.get("mode") or "repair")
    if mode == "rank":
        return _run_rank(inputs, plan)
    return _run_repair(inputs, plan)


def _run_repair(inputs: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    candidate = inputs.get("candidate")
    before = validate_constraint_geometry_ir(candidate, plan)
    repaired = repair_constraint_geometry_ir(candidate, plan)
    after = validate_constraint_geometry_ir(repaired, plan)
    constraints = repaired.get("constraints", []) if isinstance(repaired, dict) else []
    points = repaired.get("points", []) if isinstance(repaired, dict) else []
    midpoint = next((item for item in points if isinstance(item, dict) and item.get("id") == "M"), None)
    active_drag = next(
        (
            str(item.get("id"))
            for item in points
            if isinstance(item, dict) and isinstance(item.get("drag"), dict)
        ),
        None,
    )
    return {
        "before_ok": before["ok"],
        "after_ok": after["ok"],
        "before_error_types": [item.get("type") for item in before["errors"]],
        "after_error_types": [item.get("type") for item in after["errors"]],
        "kept_constraint_types": sorted({str(item.get("type")) for item in constraints if isinstance(item, dict)}),
        "dropped_constraint_types": _dropped_constraint_types(candidate, repaired),
        "angle_count": len(repaired.get("angles", [])) if isinstance(repaired, dict) else 0,
        "active_drag_point": active_drag,
        "midpoint_x": midpoint.get("x") if isinstance(midpoint, dict) else None,
        "midpoint_y": midpoint.get("y") if isinstance(midpoint, dict) else None,
        "midpoint_uses_expression": isinstance(midpoint, dict)
        and (isinstance(midpoint.get("x"), dict) or isinstance(midpoint.get("y"), dict)),
    }


def _run_rank(inputs: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    candidates = inputs.get("candidates") if isinstance(inputs.get("candidates"), list) else []
    ranking = rank_constraint_geometry_ir_candidates(candidates, plan)
    selected = ranking.get("selected_ir") if isinstance(ranking.get("selected_ir"), dict) else {}
    midpoint = next((item for item in selected.get("points", []) if item.get("id") == "M"), None)
    return {
        "ranking_ok": bool(ranking.get("ok")),
        "selected_midpoint_x": midpoint.get("x") if isinstance(midpoint, dict) else None,
        "selected_midpoint_y": midpoint.get("y") if isinstance(midpoint, dict) else None,
    }


def _dropped_constraint_types(before: object, after: object) -> list[str]:
    before_types = {
        str(item.get("type"))
        for item in (before.get("constraints", []) if isinstance(before, dict) else [])
        if isinstance(item, dict)
    }
    after_types = {
        str(item.get("type"))
        for item in (after.get("constraints", []) if isinstance(after, dict) else [])
        if isinstance(item, dict)
    }
    return sorted(before_types - after_types)
