"""Generic deterministic completion of missing intermediate transform evidence."""

from __future__ import annotations

import json
from typing import Any

from aetherviz_service.aetherviz.tools.recomposition_ir import normalize_geometry_ir
from aetherviz_service.aetherviz.tools.recomposition_semantics import (
    evaluate_recomposition_semantics,
)


def complete_intermediate_waypoints(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    """Complete only failed intermediate stages without inferring topic-specific geometry."""
    if not isinstance(ir, dict):
        return {"ok": False, "changed": False, "ir": None, "reason": "candidate_not_object"}
    normalized = normalize_geometry_ir(ir, plan)
    before = evaluate_recomposition_semantics(normalized, plan)
    failed_stage_ids = {
        str(error.get("name") or "")
        for error in before.get("errors", [])
        if error.get("type") == "missing_intermediate_geometry_stage"
    }
    other_errors = [
        error
        for error in before.get("errors", [])
        if error.get("type") != "missing_intermediate_geometry_stage"
    ]
    if other_errors:
        return {
            "ok": False,
            "changed": False,
            "ir": normalized,
            "reason": "non_waypoint_semantic_errors",
            "error_types": sorted({str(error.get("type")) for error in other_errors}),
            "before": before,
        }
    if not failed_stage_ids:
        return {
            "ok": before["ok"],
            "changed": False,
            "ir": normalized,
            "reason": "waypoints_already_sufficient",
            "before": before,
            "after": before,
        }

    completed = json.loads(json.dumps(normalized, ensure_ascii=False))
    requirements = _stage_requirements(plan)
    required_times = {round(float(stage.get("at", 0)), 6) for stage in requirements}
    completed_stages: list[str] = []
    for stage_index, stage in enumerate(requirements):
        stage_id = str(stage.get("id") or "")
        role = str(stage.get("role") or "")
        if role != "intermediate" or stage_id not in failed_stage_ids:
            continue
        at = float(stage.get("at", 0.5))
        for piece_index, piece in enumerate(completed.get("pieces", [])):
            if isinstance(piece, dict):
                _upsert_waypoint(
                    piece,
                    at,
                    stage_index=stage_index,
                    piece_index=piece_index,
                    required_times=required_times,
                )
        completed_stages.append(stage_id)

    after = evaluate_recomposition_semantics(completed, plan)
    return {
        "ok": after["ok"],
        "changed": bool(completed_stages),
        "ir": completed,
        "reason": "waypoints_completed" if after["ok"] else "waypoint_completion_insufficient",
        "completed_stage_ids": completed_stages,
        "before": before,
        "after": after,
    }


def _upsert_waypoint(
    piece: dict[str, Any],
    at: float,
    *,
    stage_index: int,
    piece_index: int,
    required_times: set[float],
) -> None:
    source = piece.get("source") if isinstance(piece.get("source"), dict) else {}
    target = piece.get("target") if isinstance(piece.get("target"), dict) else {}
    existing = {
        round(float(frame.get("at")), 6): frame
        for frame in piece.get("keyframes", [])
        if isinstance(frame, dict) and _is_number(frame.get("at"))
    }
    magnitude = 36 + stage_index * 12
    direction = -1 if (stage_index + piece_index) % 2 else 1
    direct_x = _lerp(source.get("x", 0), target.get("x", 0), at)
    direct_y = _lerp(source.get("y", 0), target.get("y", 0), at)
    waypoint = {
        "at": at,
        "x": _bounded_offset(direct_x, 24, 936, magnitude * direction),
        "y": _bounded_offset(direct_y, 24, 536, -magnitude * 0.7 * direction),
        "rotation": {
            "op": "add",
            "args": [_lerp(source.get("rotation", 0), target.get("rotation", 0), at), 18 * direction],
        },
        "scale": _lerp(source.get("scale", 1), target.get("scale", 1), at),
        "opacity": _lerp(source.get("opacity", 1), target.get("opacity", 1), at),
    }
    existing[round(at, 6)] = waypoint
    existing[0.0] = {"at": 0, **source}
    existing[1.0] = {"at": 1, **target}
    piece["keyframes"] = [existing[value] for value in sorted(required_times) if value in existing]


def _lerp(source: object, target: object, at: float) -> object:
    if source == target:
        return source
    return {
        "op": "add",
        "args": [source, {"op": "mul", "args": [{"op": "sub", "args": [target, source]}, at]}],
    }


def _bounded_offset(value: object, minimum: float, maximum: float, offset: float) -> dict[str, Any]:
    return {
        "op": "clamp",
        "args": [{"op": "add", "args": [value, offset]}, minimum, maximum],
    }


def _stage_requirements(plan: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    proof = spec.get("proof_constraints") if isinstance(spec.get("proof_constraints"), dict) else {}
    return [item for item in proof.get("stage_requirements", []) if isinstance(item, dict)]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
