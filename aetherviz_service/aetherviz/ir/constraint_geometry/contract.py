"""Deterministic contract for parameter-driven Euclidean constructions."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from hashlib import sha256
from typing import Any

CONSTRAINT_GEOMETRY_IR_VERSION = "aetherviz.constraint-geometry-ir.v1.1"
CONSTRAINT_GEOMETRY_IR_MAX_CHARS = 20_000
EXPRESSION_OPS = frozenset(
    {
        "add",
        "sub",
        "mul",
        "div",
        "pow",
        "min",
        "max",
        "neg",
        "abs",
        "sqrt",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan2",
        "deg_to_rad",
    }
)
CONSTRAINT_TYPES = frozenset(
    {
        "coincident",
        "horizontal",
        "vertical",
        "parallel",
        "perpendicular",
        "equal_length",
        "point_on_circle",
        "midpoint",
        "collinear",
        "tangent",
        "equal_angle",
        "supplementary",
    }
)
DRAG_MODES = frozenset({"x", "y", "angle_on_circle", "segment_parameter"})
CONSTRAINT_REF_KINDS: dict[str, tuple[str, ...]] = {
    "coincident": ("point", "point"),
    "horizontal": ("point", "point"),
    "vertical": ("point", "point"),
    "parallel": ("line", "line"),
    "perpendicular": ("line", "line"),
    "equal_length": ("line", "line"),
    "point_on_circle": ("point", "circle"),
    "midpoint": ("point", "point", "point"),
    "collinear": ("point", "point", "point"),
    "tangent": ("line", "circle", "point"),
    "equal_angle": ("angle", "angle"),
    "supplementary": ("angle", "angle"),
}


class ConstraintGeometryIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "constraint_geometry_ir_invalid")


def _expression_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "number"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["state"],
                "properties": {"state": {"type": "string", "minLength": 1, "maxLength": 64}},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "args"],
                "properties": {
                    "op": {"type": "string", "enum": sorted(EXPRESSION_OPS)},
                    "args": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"$ref": "#/$defs/expression"}},
                },
            },
        ]
    }


def constraint_geometry_ir_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": {"expression": _expression_schema()},
        "required": [
            "version",
            "viewport",
            "animation",
            "points",
            "lines",
            "circles",
            "angles",
            "loci",
            "constraints",
            "observation",
        ],
        "properties": {
            "version": {"type": "string", "enum": [CONSTRAINT_GEOMETRY_IR_VERSION]},
            "viewport": {
                "type": "object",
                "additionalProperties": False,
                "required": ["x_min", "x_max", "y_min", "y_max"],
                "properties": {key: {"type": "number"} for key in ("x_min", "x_max", "y_min", "y_max")},
            },
            "animation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["variable", "from", "to", "default", "duration"],
                "properties": {
                    "variable": {"type": "string", "minLength": 1, "maxLength": 64},
                    "from": {"type": "number"},
                    "to": {"type": "number"},
                    "default": {"type": "number"},
                    "duration": {"type": "number", "minimum": 2, "maximum": 12},
                },
            },
            "points": {
                "type": "array",
                "minItems": 2,
                "maxItems": 24,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label", "x", "y"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "label": {"type": "string", "maxLength": 24},
                        "x": {"$ref": "#/$defs/expression"},
                        "y": {"$ref": "#/$defs/expression"},
                        "drag": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["state", "mode"],
                            "properties": {
                                "state": {"type": "string", "minLength": 1, "maxLength": 64},
                                "mode": {"type": "string", "enum": sorted(DRAG_MODES)},
                                "ref": {"type": "string", "maxLength": 64},
                                "unit": {"type": "string", "enum": ["scalar", "radian", "degree"]},
                            },
                        },
                    },
                },
            },
            "lines": {
                "type": "array",
                "maxItems": 32,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "from", "to", "kind", "label"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "kind": {"type": "string", "enum": ["segment"]},
                        "label": {"type": "string", "maxLength": 40},
                    },
                },
            },
            "circles": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "center", "radius", "label"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "center": {"type": "string"},
                        "radius": {"$ref": "#/$defs/expression"},
                        "label": {"type": "string", "maxLength": 40},
                    },
                },
            },
            "angles": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "from", "vertex", "to", "label", "precision"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "from": {"type": "string"},
                        "vertex": {"type": "string"},
                        "to": {"type": "string"},
                        "label": {"type": "string", "maxLength": 40},
                        "precision": {"type": "integer", "minimum": 0, "maximum": 3},
                    },
                },
            },
            "loci": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "point", "label", "max_samples", "min_distance"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "point": {"type": "string"},
                        "label": {"type": "string", "maxLength": 40},
                        "max_samples": {"type": "integer", "minimum": 16, "maximum": 800},
                        "min_distance": {"type": "number", "minimum": 0.0001, "maximum": 1},
                    },
                },
            },
            "constraints": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "refs", "tolerance"],
                    "properties": {
                        "type": {"type": "string", "enum": sorted(CONSTRAINT_TYPES)},
                        "refs": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}},
                        "tolerance": {"type": "number", "minimum": 0.000001, "maximum": 0.001},
                    },
                },
            },
            "observation": {"type": "string", "minLength": 1, "maxLength": 240},
        },
    }


def constraint_geometry_ir_candidates_response_schema() -> dict[str, Any]:
    candidate = constraint_geometry_ir_response_schema()
    definitions = candidate.pop("$defs")
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": definitions,
        "required": ["candidates"],
        "properties": {"candidates": {"type": "array", "minItems": 2, "maxItems": 2, "items": candidate}},
    }


def normalize_constraint_geometry_ir(ir: object, plan: dict[str, Any]) -> object:
    if not isinstance(ir, dict):
        return ir
    candidate = deepcopy(ir)
    candidate.setdefault("angles", [])
    candidate.setdefault("loci", [])
    variables = _plan_variables(plan)
    animation = candidate.get("animation") if isinstance(candidate.get("animation"), dict) else {}
    selected = next(
        (item for item in variables if item["name"] == animation.get("variable")), variables[0] if variables else None
    )
    if selected:
        animation.update(
            {
                "variable": selected["name"],
                "from": selected["min"],
                "to": selected["max"],
                "default": selected["default"],
            }
        )
    candidate["animation"] = animation
    return candidate


def repair_constraint_geometry_ir(ir: object, plan: dict[str, Any]) -> object:
    """Apply bounded structural fixes before semantic validation or model repair."""
    candidate = normalize_constraint_geometry_ir(ir, plan)
    if not isinstance(candidate, dict):
        return candidate
    variables = {item["name"] for item in _plan_variables(plan)}
    points = _dict_items(candidate.get("points"))
    lines = _dict_items(candidate.get("lines"))
    circles = _dict_items(candidate.get("circles"))
    angles = _dict_items(candidate.get("angles"))
    loci = _dict_items(candidate.get("loci"))
    constraints = _dict_items(candidate.get("constraints"))
    point_ids = {str(item.get("id") or "") for item in points if item.get("id")}
    line_ids = {str(item.get("id") or "") for item in lines if item.get("id")}
    circle_ids = {str(item.get("id") or "") for item in circles if item.get("id")}
    points_by_id = {str(item.get("id") or ""): item for item in points if item.get("id")}
    for point in points:
        drag = point.get("drag") if isinstance(point.get("drag"), dict) else None
        if drag is None:
            continue
        mode, state_name = drag.get("mode"), drag.get("state")
        if mode not in DRAG_MODES or state_name not in variables:
            point.pop("drag", None)
            continue
        required = (
            [point.get("x")] if mode == "x" else [point.get("y")] if mode == "y" else [point.get("x"), point.get("y")]
        )
        if state_name not in set().union(*(_expression_states(expr) for expr in required)):
            point.pop("drag", None)
    # Models often emit B.x / C.y aliases; rewrite them to the referenced point fields.
    for point in points:
        point_id = str(point.get("id") or "")
        for key in ("x", "y"):
            point[key] = _rewrite_point_field_aliases(point.get(key), points_by_id, variables, {point_id})
    for circle in circles:
        circle["radius"] = _rewrite_point_field_aliases(circle.get("radius"), points_by_id, variables, set())
    # Rewrite midpoint coordinates from endpoints (constants or shared expressions).
    for item in constraints:
        if item.get("type") != "midpoint":
            continue
        refs = [str(ref) for ref in item.get("refs", [])] if isinstance(item.get("refs"), list) else []
        if len(refs) != 3:
            continue
        midpoint, left, right = (points_by_id.get(ref) for ref in refs)
        if midpoint is None or left is None or right is None:
            continue
        midpoint["x"] = _midpoint_coordinate(left.get("x"), right.get("x"))
        midpoint["y"] = _midpoint_coordinate(left.get("y"), right.get("y"))
    # Re-check drag activity after coordinate rewrites.
    for point in points:
        drag = point.get("drag") if isinstance(point.get("drag"), dict) else None
        if drag is None:
            continue
        mode, state_name = drag.get("mode"), drag.get("state")
        required = (
            [point.get("x")] if mode == "x" else [point.get("y")] if mode == "y" else [point.get("x"), point.get("y")]
        )
        if state_name not in set().union(*(_expression_states(expr) for expr in required)):
            point.pop("drag", None)
    kept_angles: list[dict[str, Any]] = []
    for angle in angles:
        angle_points = [angle.get(key) for key in ("from", "vertex", "to")]
        if (
            len(set(angle_points)) == 3
            and all(ref in point_ids for ref in angle_points)
            and isinstance(angle.get("precision"), int)
            and 0 <= angle["precision"] <= 3
        ):
            kept_angles.append(angle)
    angle_ids = {str(item.get("id") or "") for item in kept_angles if item.get("id")}
    kind_sets = {
        "point": point_ids,
        "line": line_ids,
        "circle": circle_ids,
        "angle": angle_ids,
    }
    kept_constraints: list[dict[str, Any]] = []
    for item in constraints:
        kind = str(item.get("type") or "")
        expected = CONSTRAINT_REF_KINDS.get(kind)
        refs = [str(ref) for ref in item.get("refs", [])] if isinstance(item.get("refs"), list) else []
        if expected is None or len(refs) != len(expected):
            continue
        if any(ref not in kind_sets[kind_name] for ref, kind_name in zip(refs, expected, strict=True)):
            continue
        kept_constraints.append(item)
    # Do not turn a wholly invalid constraint set into a valid unconstrained scene.
    if constraints and not kept_constraints:
        kept_constraints = constraints
    candidate["points"] = points
    candidate["lines"] = lines
    candidate["circles"] = circles
    candidate["angles"] = kept_angles
    candidate["loci"] = loci
    candidate["constraints"] = kept_constraints
    return candidate


def _dict_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _constant_number(expression: object) -> float | None:
    if isinstance(expression, bool):
        return None
    if isinstance(expression, (int, float)):
        value = float(expression)
        return value if math.isfinite(value) else None
    if isinstance(expression, dict) and expression.get("op") == "neg":
        args = expression.get("args")
        if isinstance(args, list) and len(args) == 1:
            inner = _constant_number(args[0])
            return None if inner is None else -inner
    return None


def _midpoint_coordinate(left: object, right: object) -> object:
    left_value, right_value = _constant_number(left), _constant_number(right)
    if left_value is not None and right_value is not None:
        return (left_value + right_value) / 2
    return {"op": "div", "args": [{"op": "add", "args": [deepcopy(left), deepcopy(right)]}, 2]}


def _rewrite_point_field_aliases(
    expression: object,
    points_by_id: dict[str, dict[str, Any]],
    variables: set[str],
    blocked: set[str],
    depth: int = 0,
) -> object:
    """Replace illegal ``{\"state\":\"A.x\"}`` aliases with the referenced point field."""
    if depth > 12:
        return expression
    if isinstance(expression, dict) and set(expression) == {"state"}:
        name = str(expression["state"])
        if name in variables:
            return expression
        if "." not in name:
            return expression
        point_id, field = name.rsplit(".", 1)
        if field not in {"x", "y"} or point_id not in points_by_id or point_id in blocked:
            return expression
        source = points_by_id[point_id].get(field)
        return _rewrite_point_field_aliases(source, points_by_id, variables, blocked | {point_id}, depth + 1)
    if isinstance(expression, dict) and isinstance(expression.get("args"), list):
        rewritten = dict(expression)
        rewritten["args"] = [
            _rewrite_point_field_aliases(item, points_by_id, variables, blocked, depth + 1)
            for item in expression["args"]
        ]
        return rewritten
    return expression


def validate_constraint_geometry_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_constraint_geometry_ir(ir, plan)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(normalized, dict):
        return _report([{"type": "invalid_constraint_geometry_ir", "message": "约束几何 IR 必须是对象"}], [])
    if normalized.get("version") != CONSTRAINT_GEOMETRY_IR_VERSION:
        errors.append({"type": "unsupported_constraint_geometry_ir_version", "message": "约束几何 IR 版本不受支持"})
    viewport = normalized.get("viewport") if isinstance(normalized.get("viewport"), dict) else {}
    try:
        bounds = [float(viewport[key]) for key in ("x_min", "x_max", "y_min", "y_max")]
        if not all(math.isfinite(value) for value in bounds) or bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        errors.append({"type": "invalid_geometry_viewport", "message": "数学视口必须是有限且严格递增的范围"})
    variables = {item["name"]: item for item in _plan_variables(plan)}
    animation = normalized.get("animation") if isinstance(normalized.get("animation"), dict) else {}
    variable = str(animation.get("variable") or "")
    if not variables or variable not in variables:
        errors.append({"type": "unknown_geometry_animation_state", "message": "动画变量必须引用计划中的可调变量"})
    points = normalized.get("points") if isinstance(normalized.get("points"), list) else []
    lines = normalized.get("lines") if isinstance(normalized.get("lines"), list) else []
    circles = normalized.get("circles") if isinstance(normalized.get("circles"), list) else []
    angles = normalized.get("angles") if isinstance(normalized.get("angles"), list) else []
    loci = normalized.get("loci") if isinstance(normalized.get("loci"), list) else []
    constraints = normalized.get("constraints") if isinstance(normalized.get("constraints"), list) else []
    collection_sizes = {
        "points": (len(points), 2, 24),
        "lines": (len(lines), 0, 32),
        "circles": (len(circles), 0, 12),
        "angles": (len(angles), 0, 16),
        "loci": (len(loci), 0, 4),
        "constraints": (len(constraints), 1, 24),
    }
    for name, (size, minimum, maximum) in collection_sizes.items():
        if not minimum <= size <= maximum:
            errors.append(
                {
                    "type": "invalid_geometry_collection_size",
                    "message": f"{name} 数量必须在 {minimum} 到 {maximum} 之间",
                }
            )
    point_ids = _unique_ids(points, "point", errors)
    line_ids = _unique_ids(lines, "line", errors)
    circle_ids = _unique_ids(circles, "circle", errors)
    angle_ids = _unique_ids(angles, "angle", errors)
    locus_ids = _unique_ids(loci, "locus", errors)
    object_id_groups = (point_ids, line_ids, circle_ids, angle_ids, locus_ids)
    if len(set().union(*object_id_groups)) != sum(len(group) for group in object_id_groups):
        errors.append({"type": "duplicate_geometry_object_id", "message": "几何对象 id 必须全局唯一"})
    for point in points:
        drag = point.get("drag") if isinstance(point, dict) and isinstance(point.get("drag"), dict) else None
        if drag is None:
            continue
        mode, state_name, ref = drag.get("mode"), drag.get("state"), drag.get("ref")
        if mode not in DRAG_MODES or state_name not in variables:
            errors.append({"type": "invalid_geometry_drag_binding", "message": "拖拽必须绑定计划状态和受支持模式"})
        if mode == "angle_on_circle" and ref not in circle_ids:
            errors.append({"type": "invalid_geometry_drag_circle", "message": "圆周拖拽必须引用已声明圆"})
        if mode == "segment_parameter" and ref not in line_ids:
            errors.append({"type": "invalid_geometry_drag_segment", "message": "线段拖拽必须引用已声明线段"})
        required_expressions = (
            [point.get("x")] if mode == "x" else [point.get("y")] if mode == "y" else [point.get("x"), point.get("y")]
        )
        if state_name not in set().union(*(_expression_states(expr) for expr in required_expressions)):
            errors.append({"type": "inactive_geometry_drag_binding", "message": "拖拽状态必须实际驱动被拖拽点坐标"})
    for line in lines:
        if (
            not isinstance(line, dict)
            or line.get("from") not in point_ids
            or line.get("to") not in point_ids
            or line.get("from") == line.get("to")
        ):
            errors.append({"type": "invalid_geometry_line_reference", "message": "线必须引用两个不同的已声明点"})
    for circle in circles:
        if not isinstance(circle, dict) or circle.get("center") not in point_ids:
            errors.append({"type": "invalid_geometry_circle_reference", "message": "圆必须引用已声明圆心"})
    for angle in angles:
        angle_points = [angle.get(key) for key in ("from", "vertex", "to")] if isinstance(angle, dict) else []
        if len(set(angle_points)) != 3 or any(ref not in point_ids for ref in angle_points):
            errors.append({"type": "invalid_geometry_angle_reference", "message": "角必须引用三个不同的已声明点"})
        if (
            not isinstance(angle, dict)
            or not isinstance(angle.get("precision"), int)
            or not 0 <= angle["precision"] <= 3
        ):
            errors.append({"type": "invalid_geometry_angle_precision", "message": "角度精度必须是 0 到 3 的整数"})
    for locus in loci:
        if not isinstance(locus, dict) or locus.get("point") not in point_ids:
            errors.append({"type": "invalid_geometry_locus_reference", "message": "轨迹必须引用已声明动点"})
            continue
        try:
            max_samples, min_distance = int(locus.get("max_samples")), float(locus.get("min_distance"))
            if (
                max_samples != locus.get("max_samples")
                or not 16 <= max_samples <= 800
                or not 0.0001 <= min_distance <= 1
            ):
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"type": "invalid_geometry_locus_bounds", "message": "轨迹容量或最小采样距离超出限制"})
    refs = point_ids | line_ids | circle_ids | angle_ids
    for item in constraints:
        if not isinstance(item, dict) or item.get("type") not in CONSTRAINT_TYPES:
            errors.append({"type": "invalid_geometry_constraint", "message": "几何约束类型不受支持"})
            continue
        if any(ref not in refs for ref in item.get("refs", [])):
            errors.append({"type": "unknown_geometry_constraint_ref", "message": "几何约束引用了未知对象"})
    if variables and variable in variables:
        samples = _sample_states(variables, variable)
        for state in samples:
            try:
                evaluated = _evaluate_scene(normalized, state)
                _check_scene_bounds(evaluated, viewport)
                for constraint in constraints:
                    _check_constraint(constraint, evaluated)
            except ValueError as exc:
                errors.append({"type": "geometry_invariant_failed", "message": str(exc)[:240], "state": state})
                break
    serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > CONSTRAINT_GEOMETRY_IR_MAX_CHARS:
        errors.append({"type": "constraint_geometry_ir_too_long", "message": "约束几何 IR 超过长度上限"})
    return _report(errors, warnings)


def rank_constraint_geometry_ir_candidates(candidates: list[object], plan: dict[str, Any]) -> dict[str, Any]:
    ranked = []
    for index, candidate in enumerate(candidates):
        normalized = repair_constraint_geometry_ir(candidate, plan)
        report = validate_constraint_geometry_ir(normalized, plan)
        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ranked.append(
            {
                "index": index,
                "ir": normalized,
                "report": report,
                "errors": len(report["errors"]),
                "warnings": len(report["warnings"]),
                "chars": len(serialized),
                "fingerprint": sha256(serialized.encode()).hexdigest(),
            }
        )
    ranked.sort(
        key=lambda item: (
            not item["report"]["ok"],
            item["errors"],
            item["warnings"],
            item["chars"],
            item["fingerprint"],
        )
    )
    selected = next((item for item in ranked if item["report"]["ok"]), None)
    repair = ranked[0] if ranked else None
    return {
        "ok": selected is not None,
        "selected_ir": selected["ir"] if selected else None,
        "repair_candidate": repair["ir"] if repair else None,
        "repair_report": repair["report"] if repair else None,
    }


def parse_constraint_geometry_ir(raw: str) -> object:
    text = raw.strip()
    if "```" in text:
        text = text.split("```", 2)[1].removeprefix("json").strip()
    return json.loads(text)


def parse_constraint_geometry_ir_candidates(raw: str) -> list[object]:
    payload = parse_constraint_geometry_ir(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise ValueError("constraint_geometry_candidates_missing")
    return payload["candidates"]


def compile_constraint_geometry_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    normalized = repair_constraint_geometry_ir(ir, plan)
    report = validate_constraint_geometry_ir(normalized, plan)
    if not report["ok"] or not isinstance(normalized, dict):
        raise ConstraintGeometryIRValidationError(report)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _plan_variables(plan: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    result = []
    for item in spec.get("variables", []):
        if not isinstance(item, dict) or item.get("computed") or not item.get("name"):
            continue
        try:
            minimum, maximum = float(item.get("min", 0)), float(item.get("max", 1))
            default = float(item.get("default", minimum))
            if not all(math.isfinite(value) for value in (minimum, maximum, default)) or minimum >= maximum:
                continue
            result.append(
                {
                    "name": str(item["name"]),
                    "label": str(item.get("label") or item["name"]),
                    "min": minimum,
                    "max": maximum,
                    "default": min(maximum, max(minimum, default)),
                    "step": float(item.get("step", (maximum - minimum) / 100)),
                    "unit": str(item.get("unit") or ""),
                }
            )
        except (TypeError, ValueError):
            continue
    return result


def _unique_ids(items: list[object], kind: str, errors: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for item in items:
        identifier = str(item.get("id") or "") if isinstance(item, dict) else ""
        if not identifier or identifier in result:
            errors.append({"type": f"invalid_{kind}_id", "message": f"{kind} id 缺失或重复"})
        else:
            result.add(identifier)
    return result


def _expression_states(expression: object) -> set[str]:
    if isinstance(expression, dict) and set(expression) == {"state"}:
        return {str(expression["state"])}
    if isinstance(expression, dict) and isinstance(expression.get("args"), list):
        return set().union(*(_expression_states(item) for item in expression["args"]))
    return set()


def _sample_states(variables: dict[str, dict[str, Any]], animation_variable: str) -> list[dict[str, float]]:
    base = {name: item["default"] for name, item in variables.items()}
    source = variables[animation_variable]
    return [
        {**base, animation_variable: source["min"] + (source["max"] - source["min"]) * ratio}
        for ratio in (0, 0.25, 0.5, 0.75, 1)
    ]


def _evaluate(expression: object, state: dict[str, float], depth: int = 0) -> float:
    if depth > 12:
        raise ValueError("表达式嵌套过深")
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        value = float(expression)
    elif isinstance(expression, dict) and set(expression) == {"state"}:
        if expression["state"] not in state:
            raise ValueError(f"表达式引用未知状态：{expression['state']}")
        value = float(state[expression["state"]])
    elif (
        isinstance(expression, dict)
        and expression.get("op") in EXPRESSION_OPS
        and isinstance(expression.get("args"), list)
    ):
        op, values = expression["op"], [_evaluate(item, state, depth + 1) for item in expression["args"]]
        try:
            value = {
                "add": lambda: sum(values),
                "sub": lambda: values[0] - sum(values[1:]),
                "mul": lambda: math.prod(values),
                "div": lambda: values[0] / math.prod(values[1:]),
                "pow": lambda: values[0] ** values[1],
                "min": lambda: min(values),
                "max": lambda: max(values),
                "neg": lambda: -values[0],
                "abs": lambda: abs(values[0]),
                "sqrt": lambda: math.sqrt(values[0]),
                "sin": lambda: math.sin(values[0]),
                "cos": lambda: math.cos(values[0]),
                "tan": lambda: math.tan(values[0]),
                "asin": lambda: math.asin(values[0]),
                "acos": lambda: math.acos(values[0]),
                "atan2": lambda: math.atan2(values[0], values[1]),
                "deg_to_rad": lambda: math.radians(values[0]),
            }[op]()
        except (ArithmeticError, IndexError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"表达式无法计算：{op}") from exc
    else:
        raise ValueError("表达式结构不受支持")
    if not math.isfinite(value):
        raise ValueError("表达式结果不是有限数")
    return value


def _evaluate_scene(ir: dict[str, Any], state: dict[str, float]) -> dict[str, Any]:
    points = {item["id"]: (_evaluate(item["x"], state), _evaluate(item["y"], state)) for item in ir.get("points", [])}
    lines = {
        item["id"]: (points[item["from"]], points[item["to"]])
        for item in ir.get("lines", [])
        if item.get("from") in points and item.get("to") in points
    }
    circles = {
        item["id"]: (points[item["center"]], _evaluate(item["radius"], state))
        for item in ir.get("circles", [])
        if item.get("center") in points
    }
    if any(radius <= 0 for _, radius in circles.values()):
        raise ValueError("圆半径必须始终为正数")
    angles = {
        item["id"]: _angle_value(points[item["from"]], points[item["vertex"]], points[item["to"]])
        for item in ir.get("angles", [])
        if item.get("from") in points and item.get("vertex") in points and item.get("to") in points
    }
    return {"points": points, "lines": lines, "circles": circles, "angles": angles}


def _angle_value(start: tuple[float, float], vertex: tuple[float, float], end: tuple[float, float]) -> float:
    first = (start[0] - vertex[0], start[1] - vertex[1])
    second = (end[0] - vertex[0], end[1] - vertex[1])
    first_length, second_length = math.hypot(*first), math.hypot(*second)
    if first_length <= 1e-12 or second_length <= 1e-12:
        raise ValueError("角的射线长度不能为零")
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_length * second_length)
    return math.acos(max(-1.0, min(1.0, cosine)))


def _check_scene_bounds(scene: dict[str, Any], viewport: dict[str, Any]) -> None:
    if not all(key in viewport for key in ("x_min", "x_max", "y_min", "y_max")):
        return
    margin_x = (float(viewport["x_max"]) - float(viewport["x_min"])) * 0.05
    margin_y = (float(viewport["y_max"]) - float(viewport["y_min"])) * 0.05
    for identifier, (x, y) in scene["points"].items():
        if not (
            float(viewport["x_min"]) - margin_x <= x <= float(viewport["x_max"]) + margin_x
            and float(viewport["y_min"]) - margin_y <= y <= float(viewport["y_max"]) + margin_y
        ):
            raise ValueError(f"点 {identifier} 在动画边界超出数学视口")


def _check_constraint(item: dict[str, Any], scene: dict[str, Any]) -> None:
    kind, refs = item.get("type"), item.get("refs", [])
    tolerance = float(item.get("tolerance", 0.001))
    points, lines, circles, angles = scene["points"], scene["lines"], scene["circles"], scene["angles"]

    def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def vector(line: tuple[tuple[float, float], tuple[float, float]]) -> tuple[float, float]:
        return line[1][0] - line[0][0], line[1][1] - line[0][1]

    ok = False
    try:
        if kind == "coincident" and len(refs) == 2:
            ok = distance(points[refs[0]], points[refs[1]]) <= tolerance
        elif kind in {"horizontal", "vertical"} and len(refs) == 2:
            a, b = points[refs[0]], points[refs[1]]
            ok = abs((a[1] - b[1]) if kind == "horizontal" else (a[0] - b[0])) <= tolerance
        elif kind in {"parallel", "perpendicular"} and len(refs) == 2:
            u, v = vector(lines[refs[0]]), vector(lines[refs[1]])
            scale = max(1.0, math.hypot(*u) * math.hypot(*v))
            value = u[0] * v[1] - u[1] * v[0] if kind == "parallel" else u[0] * v[0] + u[1] * v[1]
            ok = abs(value) <= tolerance * scale
        elif kind == "equal_length" and len(refs) == 2:
            ok = abs(distance(*lines[refs[0]]) - distance(*lines[refs[1]])) <= tolerance
        elif kind == "point_on_circle" and len(refs) == 2:
            center, radius = circles[refs[1]]
            ok = abs(distance(points[refs[0]], center) - radius) <= tolerance
        elif kind == "midpoint" and len(refs) == 3:
            m, a, b = (points[ref] for ref in refs)
            ok = distance(m, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)) <= tolerance
        elif kind == "collinear" and len(refs) == 3:
            a, b, c = (points[ref] for ref in refs)
            ok = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) <= tolerance
        elif kind == "tangent" and len(refs) == 3:
            line, (center, radius), point = lines[refs[0]], circles[refs[1]], points[refs[2]]
            direction = vector(line)
            direction_length = math.hypot(*direction)
            radial = (point[0] - center[0], point[1] - center[1])
            on_circle = abs(distance(point, center) - radius) <= tolerance
            on_line = abs(
                (point[0] - line[0][0]) * direction[1] - (point[1] - line[0][1]) * direction[0]
            ) <= tolerance * max(1.0, direction_length)
            perpendicular = abs(radial[0] * direction[0] + radial[1] * direction[1]) <= tolerance * max(
                1.0, radius * direction_length
            )
            ok = on_circle and on_line and perpendicular
        elif kind == "equal_angle" and len(refs) == 2:
            ok = abs(angles[refs[0]] - angles[refs[1]]) <= tolerance
        elif kind == "supplementary" and len(refs) == 2:
            ok = abs(angles[refs[0]] + angles[refs[1]] - math.pi) <= tolerance
    except (KeyError, TypeError, ValueError):
        ok = False
    if not ok:
        raise ValueError(f"约束 {kind} 在采样状态下不成立：{','.join(str(ref) for ref in refs)}")


def _report(errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else ("warning" if warnings else "ok"),
        "summary": f"发现 {len(errors)} 个错误，{len(warnings)} 个提示"
        if errors or warnings
        else "约束几何 IR 检查通过",
        "errors": errors,
        "warnings": warnings,
    }
