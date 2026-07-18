"""Deterministic contract for discrete regular-polygon geometry scenes."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from hashlib import sha256
from typing import Any

PARAMETRIC_GEOMETRY_IR_VERSION = "aetherviz.parametric-geometry-ir.v1"
PARAMETRIC_GEOMETRY_IR_MAX_CHARS = 8_000
POLYGON_MODES = {"inscribed", "circumscribed"}
MEASURE_TYPES = {"circle_circumference", "polygon_perimeter", "absolute_error", "relative_error"}
INVARIANT_TYPES = {"vertex_on_circle", "regular_polygon", "bounded_by_circle", "monotonic_convergence"}


class ParametricGeometryIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "parametric_geometry_ir_invalid")


def parametric_geometry_ir_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "state", "circle", "polygons", "measures", "animation", "invariants"],
        "properties": {
            "version": {"type": "string", "enum": [PARAMETRIC_GEOMETRY_IR_VERSION]},
            "state": {
                "type": "object",
                "additionalProperties": False,
                "required": ["variable", "label", "minimum", "maximum", "default", "step", "unit"],
                "properties": {
                    "variable": {"type": "string", "minLength": 1, "maxLength": 64},
                    "label": {"type": "string", "minLength": 1, "maxLength": 80},
                    "minimum": {"type": "integer", "minimum": 3, "maximum": 360},
                    "maximum": {"type": "integer", "minimum": 3, "maximum": 360},
                    "default": {"type": "integer", "minimum": 3, "maximum": 360},
                    "step": {"type": "integer", "minimum": 1, "maximum": 60},
                    "unit": {"type": "string", "maxLength": 16},
                },
            },
            "circle": {
                "type": "object",
                "additionalProperties": False,
                "required": ["radius", "label"],
                "properties": {
                    "radius": {"type": "number", "exclusiveMinimum": 0, "maximum": 1000},
                    "label": {"type": "string", "maxLength": 80},
                },
            },
            "polygons": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "mode", "label", "color"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "mode": {"type": "string", "enum": sorted(POLYGON_MODES)},
                        "label": {"type": "string", "minLength": 1, "maxLength": 80},
                        "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                    },
                },
            },
            "measures": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "type", "polygon", "label", "precision"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "type": {"type": "string", "enum": sorted(MEASURE_TYPES)},
                        "polygon": {"type": "string", "maxLength": 48},
                        "label": {"type": "string", "minLength": 1, "maxLength": 80},
                        "precision": {"type": "integer", "minimum": 0, "maximum": 8},
                    },
                },
            },
            "animation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["duration"],
                "properties": {"duration": {"type": "number", "minimum": 2, "maximum": 12}},
            },
            "invariants": {
                "type": "array",
                "minItems": 2,
                "maxItems": 8,
                "items": {"type": "string", "enum": sorted(INVARIANT_TYPES)},
            },
        },
    }


def parametric_geometry_ir_candidates_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": parametric_geometry_ir_response_schema(),
            }
        },
    }


def normalize_parametric_geometry_ir(ir: object, plan: dict[str, Any]) -> object:
    if not isinstance(ir, dict):
        return ir
    candidate = deepcopy(ir)
    state = candidate.get("state") if isinstance(candidate.get("state"), dict) else {}
    variables = _plan_variables(plan)
    source = next(
        (item for item in variables if item["name"] == state.get("variable")), variables[0] if variables else None
    )
    if source:
        state.update(
            {
                "variable": source["name"],
                "label": str(state.get("label") or source["label"]),
                "minimum": max(3, int(source["min"])),
                "maximum": min(360, int(source["max"])),
                "default": int(source["default"]),
                "step": max(1, int(source["step"])),
                "unit": str(source["unit"]),
            }
        )
        state["default"] = min(state["maximum"], max(state["minimum"], state["default"]))
    candidate["state"] = state
    return candidate


def validate_parametric_geometry_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_parametric_geometry_ir(ir, plan)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(normalized, dict):
        return _report([{"type": "invalid_parametric_geometry_ir", "message": "参数几何 IR 必须是对象"}], [])
    if normalized.get("version") != PARAMETRIC_GEOMETRY_IR_VERSION:
        errors.append({"type": "unsupported_parametric_geometry_ir_version", "message": "参数几何 IR 版本不受支持"})
    state = normalized.get("state") if isinstance(normalized.get("state"), dict) else {}
    try:
        minimum, maximum, default, step = (int(state[key]) for key in ("minimum", "maximum", "default", "step"))
        if minimum < 3 or maximum > 360 or minimum >= maximum or not minimum <= default <= maximum or step < 1:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        errors.append(
            {"type": "invalid_discrete_geometry_state", "message": "边数状态必须满足 3≤min<max≤360 且 default 在范围内"}
        )
    plan_names = {item["name"] for item in _plan_variables(plan)}
    if plan_names and state.get("variable") not in plan_names:
        errors.append({"type": "unknown_geometry_state", "message": "参数几何状态必须引用计划中的可调变量"})
    circle = normalized.get("circle") if isinstance(normalized.get("circle"), dict) else {}
    try:
        radius = float(circle.get("radius"))
        if not math.isfinite(radius) or radius <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append({"type": "invalid_geometry_radius", "message": "圆半径必须是有限正数"})
    polygons = normalized.get("polygons") if isinstance(normalized.get("polygons"), list) else []
    polygon_ids: set[str] = set()
    modes: set[str] = set()
    for polygon in polygons:
        if not isinstance(polygon, dict) or polygon.get("mode") not in POLYGON_MODES or not polygon.get("id"):
            errors.append({"type": "invalid_regular_polygon", "message": "正多边形必须包含唯一 id 和受支持 mode"})
            continue
        identifier = str(polygon["id"])
        if identifier in polygon_ids:
            errors.append({"type": "duplicate_regular_polygon", "message": f"正多边形 id 重复：{identifier}"})
        polygon_ids.add(identifier)
        modes.add(str(polygon["mode"]))
    measures = normalized.get("measures") if isinstance(normalized.get("measures"), list) else []
    for measure in measures:
        if not isinstance(measure, dict) or measure.get("type") not in MEASURE_TYPES:
            errors.append({"type": "invalid_geometry_measure", "message": "测量项类型不受支持"})
            continue
        if measure.get("type") != "circle_circumference" and measure.get("polygon") not in polygon_ids:
            errors.append({"type": "unknown_measure_polygon", "message": "多边形测量项必须引用已声明 polygon"})
    invariants = set(normalized.get("invariants") or [])
    if "regular_polygon" not in invariants:
        errors.append({"type": "missing_regular_polygon_invariant", "message": "参数几何 IR 必须声明 regular_polygon"})
    if "inscribed" in modes and "vertex_on_circle" not in invariants:
        errors.append(
            {"type": "missing_vertex_on_circle_invariant", "message": "内接正多边形必须声明 vertex_on_circle"}
        )
    if "monotonic_convergence" in invariants and not any(
        item.get("type") in {"absolute_error", "relative_error"} for item in measures if isinstance(item, dict)
    ):
        errors.append({"type": "missing_convergence_measure", "message": "收敛不变量必须有误差测量项"})
    serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > PARAMETRIC_GEOMETRY_IR_MAX_CHARS:
        errors.append({"type": "parametric_geometry_ir_too_long", "message": "参数几何 IR 超过长度上限"})
    return _report(errors, warnings)


def rank_parametric_geometry_ir_candidates(candidates: list[object], plan: dict[str, Any]) -> dict[str, Any]:
    ranked = []
    for index, candidate in enumerate(candidates):
        normalized = normalize_parametric_geometry_ir(candidate, plan)
        report = validate_parametric_geometry_ir(normalized, plan)
        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ranked.append(
            {
                "index": index,
                "ir": normalized,
                "report": report,
                "errors": len(report["errors"]),
                "chars": len(serialized),
                "fingerprint": sha256(serialized.encode()).hexdigest(),
            }
        )
    ranked.sort(key=lambda item: (not item["report"]["ok"], item["errors"], item["chars"], item["fingerprint"]))
    selected = next((item for item in ranked if item["report"]["ok"]), None)
    repair = ranked[0] if ranked else None
    return {
        "ok": selected is not None,
        "selected_ir": selected["ir"] if selected else None,
        "repair_candidate": repair["ir"] if repair else None,
        "repair_report": repair["report"] if repair else None,
    }


def parse_parametric_geometry_ir(raw: str) -> object:
    text = raw.strip()
    if "```" in text:
        text = text.split("```", 2)[1].removeprefix("json").strip()
    return json.loads(text)


def parse_parametric_geometry_ir_candidates(raw: str) -> list[object]:
    payload = parse_parametric_geometry_ir(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise ValueError("parametric_geometry_candidates_missing")
    return payload["candidates"]


def compile_parametric_geometry_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    normalized = normalize_parametric_geometry_ir(ir, plan)
    report = validate_parametric_geometry_ir(normalized, plan)
    if not report["ok"] or not isinstance(normalized, dict):
        raise ParametricGeometryIRValidationError(report)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _plan_variables(plan: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    result = []
    for item in spec.get("variables", []):
        if not isinstance(item, dict) or item.get("computed") or not item.get("name"):
            continue
        try:
            result.append(
                {
                    "name": str(item["name"]),
                    "label": str(item.get("label") or item["name"]),
                    "min": float(item.get("min", 3)),
                    "max": float(item.get("max", 12)),
                    "default": float(item.get("default", 3)),
                    "step": float(item.get("step", 1)),
                    "unit": str(item.get("unit") or ""),
                }
            )
        except (TypeError, ValueError):
            continue
    return result


def _report(errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else ("warning" if warnings else "ok"),
        "summary": f"发现 {len(errors)} 个错误，{len(warnings)} 个提示"
        if errors or warnings
        else "参数几何 IR 检查通过",
        "errors": errors,
        "warnings": warnings,
    }
