"""Deterministic fixtures and runners for IR stability failure-mode regression."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from aetherviz_service.aetherviz.contracts.html_stream import HtmlGenerationError
from aetherviz_service.aetherviz.ir.constraint_geometry.contract import (
    rank_constraint_geometry_ir_candidates,
    repair_constraint_geometry_ir,
    validate_constraint_geometry_ir,
)
from aetherviz_service.aetherviz.ir.coordinate_graph.contract import (
    COORDINATE_GRAPH_IR_VERSION,
    rank_coordinate_graph_ir_candidates,
)
from aetherviz_service.aetherviz.ir.data_distribution.contract import (
    DATA_DISTRIBUTION_IR_VERSION,
    rank_data_distribution_ir_candidates,
)
from aetherviz_service.aetherviz.ir.linked_coordinate.contract import (
    LINKED_COORDINATE_IR_VERSION,
    rank_linked_coordinate_ir_candidates,
)
from aetherviz_service.aetherviz.ir.recomposition.contract import build_deterministic_geometry_ir
from aetherviz_service.aetherviz.ir.recomposition.ranking import rank_geometry_ir_candidates
from aetherviz_service.aetherviz.ir.stream import (
    IRStreamResult,
    looks_like_incomplete_json,
    raise_if_incomplete_ir_stream,
)
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan


def run_ir_stability_case(inputs: dict[str, Any]) -> dict[str, Any]:
    mode = str(inputs.get("mode") or "rank")
    if mode == "incomplete_stream":
        return _run_incomplete_stream(inputs)
    if mode == "rank":
        return _run_rank(inputs)
    if mode == "constraint_repair":
        return _run_constraint_repair(inputs)
    raise ValueError(f"unsupported_ir_stability_mode:{mode}")


def _run_incomplete_stream(inputs: dict[str, Any]) -> dict[str, Any]:
    raw = str(inputs.get("raw_text") or "")
    incomplete = looks_like_incomplete_json(raw)
    code = None
    if incomplete:
        try:
            raise_if_incomplete_ir_stream(
                IRStreamResult(
                    text=raw,
                    timed_out=bool(inputs.get("timed_out")),
                    truncated_by_limit=bool(inputs.get("truncated_by_limit")),
                ),
                label="stability",
            )
        except HtmlGenerationError as exc:
            code = exc.code
    return {
        "incomplete": incomplete,
        "retryable_code": code,
        "backend": inputs.get("backend"),
    }


def _run_rank(inputs: dict[str, Any]) -> dict[str, Any]:
    backend = str(inputs.get("backend") or "")
    topic = str(inputs.get("topic") or inputs.get("case_id") or backend)
    plan = normalize_plan(inputs.get("plan") if isinstance(inputs.get("plan"), dict) else {}, topic)
    candidates = inputs.get("candidates")
    if not isinstance(candidates, list):
        candidates = _build_candidates(backend, plan, str(inputs.get("mutation") or "valid_pair"))
    ranking = _rank(backend, candidates, plan)
    selected = ranking.get("selected_ir") if isinstance(ranking.get("selected_ir"), dict) else {}
    return {
        "ranking_ok": bool(ranking.get("ok")),
        "selected_index": ranking.get("selected_index"),
        "repair_candidate_index": ranking.get("repair_candidate_index")
        if "repair_candidate_index" in ranking
        else ranking.get("repair_index"),
        "eligible_count": sum(1 for item in ranking.get("candidates", []) if item.get("eligible")),
        "candidate_count": len(ranking.get("candidates", [])),
        "selected_has_keys": sorted(selected.keys())[:8] if selected else [],
        "backend": backend,
    }


def _run_constraint_repair(inputs: dict[str, Any]) -> dict[str, Any]:
    topic = str(inputs.get("topic") or inputs.get("case_id") or "constraint")
    plan = normalize_plan(inputs.get("plan") if isinstance(inputs.get("plan"), dict) else {}, topic)
    candidate = inputs.get("candidate")
    if candidate is None:
        candidate = _constraint_candidate(plan, str(inputs.get("mutation") or "inactive_drag"))
    before = validate_constraint_geometry_ir(candidate, plan)
    repaired = repair_constraint_geometry_ir(candidate, plan)
    after = validate_constraint_geometry_ir(repaired, plan)
    return {
        "before_ok": before["ok"],
        "after_ok": after["ok"],
        "before_error_types": [item.get("type") for item in before.get("errors", [])],
        "backend": "constraint_geometry_scene",
    }


def _rank(backend: str, candidates: list[object], plan: dict[str, Any]) -> dict[str, Any]:
    if backend == "linked_coordinate_scene":
        return rank_linked_coordinate_ir_candidates(candidates, plan)
    if backend == "coordinate_graph_scene":
        return rank_coordinate_graph_ir_candidates(candidates, plan)
    if backend == "data_distribution_scene":
        return rank_data_distribution_ir_candidates(
            [item for item in candidates if isinstance(item, dict)], plan
        )
    if backend == "recomposition_scene":
        return rank_geometry_ir_candidates(candidates, plan)
    if backend == "constraint_geometry_scene":
        return rank_constraint_geometry_ir_candidates(candidates, plan)
    raise ValueError(f"unsupported_stability_backend:{backend}")


def _build_candidates(backend: str, plan: dict[str, Any], mutation: str) -> list[object]:
    if backend == "recomposition_scene":
        good = build_deterministic_geometry_ir(plan)
        bad = deepcopy(good)
        if mutation == "missing_intermediate":
            for piece in bad.get("pieces", []):
                if not isinstance(piece, dict):
                    continue
                frames = piece.get("keyframes")
                if isinstance(frames, list) and len(frames) >= 3:
                    piece["keyframes"] = [frames[0], frames[-1]]
        return [bad, good]
    if backend in {"linked_coordinate_scene", "coordinate_graph_scene"}:
        good = _linked_or_coordinate_ir(backend, plan)
        bad = deepcopy(good)
        if mutation == "break_point_on_curve" and bad.get("points"):
            bad["points"][-1]["y"] = 0
        return [bad, good]
    if backend == "data_distribution_scene":
        good = _distribution_ir(plan)
        bad = deepcopy(good)
        if mutation == "drop_required_field":
            bad["fields"] = bad.get("fields", [])[:1]
        return [bad, good]
    if backend == "constraint_geometry_scene":
        return [_constraint_candidate(plan, mutation)]
    raise ValueError(f"cannot_build_candidates:{backend}:{mutation}")


def _constraint_candidate(plan: dict[str, Any], mutation: str) -> dict[str, Any]:
    candidate = {
        "version": "aetherviz.constraint-geometry-ir.v1.1",
        "viewport": {"x_min": -4, "x_max": 4, "y_min": -1, "y_max": 5},
        "animation": {"variable": "height", "from": 1, "to": 4, "default": 2, "duration": 6},
        "points": [
            {"id": "A", "label": "A", "x": -2, "y": 0},
            {"id": "B", "label": "B", "x": 2, "y": 0},
            {"id": "C", "label": "C", "x": 0, "y": {"state": "height"}, "drag": {"state": "height", "mode": "y"}},
            {"id": "M", "label": "M", "x": 0, "y": 0},
            {"id": "H", "label": "H", "x": 0, "y": 0},
        ],
        "lines": [
            {"id": "AB", "from": "A", "to": "B", "kind": "segment", "label": "底边"},
            {"id": "CH", "from": "C", "to": "H", "kind": "segment", "label": "高"},
            {"id": "CM", "from": "C", "to": "M", "kind": "segment", "label": "中线"},
        ],
        "circles": [],
        "angles": [],
        "loci": [],
        "constraints": [
            {"type": "midpoint", "refs": ["M", "A", "B"], "tolerance": 1e-06},
            {"type": "perpendicular", "refs": ["CH", "AB"], "tolerance": 1e-06},
            {"type": "collinear", "refs": ["A", "H", "B"], "tolerance": 1e-06},
        ],
        "observation": "改变顶点高度时，中点与高约束保持成立。",
    }
    if mutation == "inactive_drag":
        candidate["points"][0]["drag"] = {"state": "height", "mode": "x"}
        candidate["constraints"].append({"type": "coincident", "refs": ["H", "AB"], "tolerance": 0.001})
    return candidate


def _operand(kind: str, ref: str = "", *, at: object = 0, axis: str = "both", value: object = 0) -> dict:
    return {"kind": kind, "ref": ref, "at": at, "axis": axis, "value": value}


def _linked_or_coordinate_ir(backend: str, plan: dict[str, Any]) -> dict[str, Any]:
    theta = {"state": "theta"}
    local_t = {"local": "t"}
    sine_theta = {"op": "sin", "args": [theta]}
    linked = {
        "version": LINKED_COORDINATE_IR_VERSION,
        "definitions": [{"name": "tau", "value": 6.283185307179586}],
        "animation": {"variable": "theta", "from": 0, "to": {"var": "tau"}, "duration": 4},
        "coordinate_systems": [
            {
                "id": "phase-space",
                "x_domain": [-1.4, 1.4],
                "y_domain": [-1.4, 1.4],
                "label": "参数轨迹",
            },
            {
                "id": "function-space",
                "x_domain": [0, {"var": "tau"}],
                "y_domain": [-1.4, 1.4],
                "label": "函数图像",
            },
        ],
        "curves": [
            {
                "id": "trajectory",
                "system": "phase-space",
                "parameter": "t",
                "parameter_unit": "radian",
                "domain": [0, {"var": "tau"}],
                "samples": 120,
                "x": {"op": "cos", "args": [local_t]},
                "y": {"op": "sin", "args": [local_t]},
                "stroke": "#2563eb",
            },
            {
                "id": "function-curve",
                "system": "function-space",
                "parameter": "t",
                "parameter_unit": "radian",
                "domain": [0, {"var": "tau"}],
                "samples": 120,
                "x": local_t,
                "y": {"op": "sin", "args": [local_t]},
                "stroke": "#10b981",
            },
        ],
        "points": [
            {
                "id": "trajectory-point",
                "system": "phase-space",
                "x": {"op": "cos", "args": [theta]},
                "y": sine_theta,
                "label": "P",
            },
            {
                "id": "function-point",
                "system": "function-space",
                "x": theta,
                "y": sine_theta,
                "label": "Q",
            },
        ],
        "links": [
            {
                "id": "value-projection",
                "from": "trajectory-point",
                "to": "function-point",
            }
        ],
        "invariants": [
            {
                "id": "trajectory-membership",
                "type": "point_on_curve",
                "left": _operand("point", "trajectory-point"),
                "right": _operand("curve_sample", "trajectory", at=theta),
                "tolerance": 0.000001,
            },
            {
                "id": "function-membership",
                "type": "point_on_curve",
                "left": _operand("point", "function-point"),
                "right": _operand("curve_sample", "function-curve", at=theta),
                "tolerance": 0.000001,
            },
            {
                "id": "shared-value",
                "type": "equal_value",
                "left": _operand("point", "trajectory-point", axis="y"),
                "right": _operand("point", "function-point", axis="y"),
                "tolerance": 0.000001,
            },
        ],
    }
    if backend == "linked_coordinate_scene":
        return linked
    graph = deepcopy(linked)
    graph["version"] = COORDINATE_GRAPH_IR_VERSION
    graph["coordinate_systems"] = [linked["coordinate_systems"][1]]
    graph["curves"] = [linked["curves"][1]]
    graph["points"] = [linked["points"][1]]
    graph["links"] = []
    graph["invariants"] = [linked["invariants"][1]]
    return graph


def _distribution_ir(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": DATA_DISTRIBUTION_IR_VERSION,
        "fields": [
            {"id": "group", "type": "category", "label": "组别"},
            {"id": "value", "type": "number", "label": "数值"},
        ],
        "rows": [
            {"id": "r1", "cells": [{"field": "group", "value": "甲"}, {"field": "value", "value": 1}]},
            {"id": "r2", "cells": [{"field": "group", "value": "乙"}, {"field": "value", "value": {"state": "n"}}]},
        ],
        "charts": [
            {
                "id": "bars",
                "type": "bar",
                "category_field": "group",
                "value_field": "value",
                "label": "柱状图",
            }
        ],
        "metrics": [{"id": "mean", "type": "mean", "field": "value"}],
        "animation": {"variable": "n", "from": 1, "to": 10, "default": 5, "duration": 4},
    }



