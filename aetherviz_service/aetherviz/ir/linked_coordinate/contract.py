"""Validated IR for linked coordinate systems and dynamic mathematical scenes."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from hashlib import sha256
from typing import Any

LINKED_COORDINATE_IR_VERSION = "aetherviz.linked-coordinate-ir.v1"
LINKED_COORDINATE_IR_MAX_CHARS = 16_000
LINKED_COORDINATE_INVARIANT_MAX_TOLERANCE = 0.001
LINKED_COORDINATE_CANVAS_WIDTH = 960
LINKED_COORDINATE_CANVAS_HEIGHT = 560
LINKED_COORDINATE_PARAMETER_UNITS = {"radian", "degree", "scalar"}
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_DESCRIPTIVE_LATIN_RE = re.compile(r"[A-Za-z]{2,}")
_OPS = {
    "add",
    "sub",
    "mul",
    "div",
    "pow",
    "mod",
    "min",
    "max",
    "clamp",
    "neg",
    "abs",
    "sqrt",
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "atan2",
    "exp",
    "log",
    "deg_to_rad",
}


class LinkedCoordinateIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "linked_coordinate_ir_invalid")


def linked_coordinate_ir_response_schema() -> dict[str, Any]:
    state_expression = {
        "anyOf": [
            {"type": "number"},
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"state": {"type": "string"}},
                "required": ["state"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"var": {"type": "string"}},
                "required": ["var"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "op": {"type": "string", "enum": sorted(_OPS)},
                    "args": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/state_expression"},
                        "minItems": 1,
                        "maxItems": 12,
                    },
                },
                "required": ["op", "args"],
            },
        ]
    }
    curve_expression = {
        "anyOf": [
            {"type": "number"},
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"state": {"type": "string"}},
                "required": ["state"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"var": {"type": "string"}},
                "required": ["var"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"local": {"type": "string"}},
                "required": ["local"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "op": {"type": "string", "enum": sorted(_OPS)},
                    "args": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/curve_expression"},
                        "minItems": 1,
                        "maxItems": 12,
                    },
                },
                "required": ["op", "args"],
            },
        ]
    }
    operand = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["point", "curve_sample", "value"]},
            "ref": {"type": "string"},
            "at": {"$ref": "#/$defs/state_expression"},
            "axis": {"type": "string", "enum": ["x", "y", "both"]},
            "value": {"$ref": "#/$defs/state_expression"},
        },
        "required": ["kind", "ref", "at", "axis", "value"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": {
            "state_expression": state_expression,
            "curve_expression": curve_expression,
            "operand": operand,
        },
        "properties": {
            "version": {"type": "string", "enum": [LINKED_COORDINATE_IR_VERSION]},
            "definitions": {
                "type": "array",
                "maxItems": 32,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"$ref": "#/$defs/state_expression"},
                    },
                    "required": ["name", "value"],
                },
            },
            "animation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "variable": {"type": "string"},
                    "from": {"$ref": "#/$defs/state_expression"},
                    "to": {"$ref": "#/$defs/state_expression"},
                    "duration": {"type": "number", "minimum": 0.5, "maximum": 20},
                    "keyframes": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "progress": {"type": "number", "minimum": 0, "maximum": 1},
                                "state": {
                                    "type": "object",
                                    "additionalProperties": {"type": "number"},
                                },
                            },
                            "required": ["progress", "state"],
                        },
                    },
                },
                "required": ["variable", "from", "to", "duration"],
            },
            "coordinate_systems": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "x_domain": {
                            "type": "array",
                            "prefixItems": [
                                {"$ref": "#/$defs/state_expression"},
                                {"$ref": "#/$defs/state_expression"},
                            ],
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "y_domain": {
                            "type": "array",
                            "prefixItems": [
                                {"$ref": "#/$defs/state_expression"},
                                {"$ref": "#/$defs/state_expression"},
                            ],
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "label": {
                            "type": "string",
                            "description": "面向学生的简体中文坐标系说明；数学符号、公式和单位可保留",
                        },
                    },
                    "required": ["id", "x_domain", "y_domain", "label"],
                },
            },
            "curves": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "system": {"type": "string"},
                        "parameter": {"type": "string"},
                        "parameter_unit": {
                            "type": "string",
                            "enum": sorted(LINKED_COORDINATE_PARAMETER_UNITS),
                        },
                        "domain": {
                            "type": "array",
                            "prefixItems": [
                                {"$ref": "#/$defs/state_expression"},
                                {"$ref": "#/$defs/state_expression"},
                            ],
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "samples": {"type": "integer", "minimum": 48, "maximum": 240},
                        "x": {"$ref": "#/$defs/curve_expression"},
                        "y": {"$ref": "#/$defs/curve_expression"},
                        "stroke": {"type": "string"},
                        "reveal": {
                            "anyOf": [
                                {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "value": {"$ref": "#/$defs/state_expression"},
                                        "from": {"$ref": "#/$defs/state_expression"},
                                        "to": {"$ref": "#/$defs/state_expression"},
                                    },
                                    "required": ["value", "from", "to"],
                                },
                                {"type": "null"},
                            ]
                        },
                    },
                    "required": [
                        "id",
                        "system",
                        "parameter",
                        "parameter_unit",
                        "domain",
                        "samples",
                        "x",
                        "y",
                        "stroke",
                        "reveal",
                    ],
                },
            },
            "points": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "system": {"type": "string"},
                        "x": {"$ref": "#/$defs/state_expression"},
                        "y": {"$ref": "#/$defs/state_expression"},
                        "radius": {"type": "number", "minimum": 2, "maximum": 16},
                        "fill": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["id", "system", "x", "y", "radius", "fill", "label"],
                },
            },
            "links": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "stroke": {"type": "string"},
                        "dash": {"type": "string"},
                    },
                    "required": ["id", "from", "to", "stroke", "dash"],
                },
            },
            "invariants": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": ["point_on_curve", "equal_value", "coincident"]},
                        "left": {"$ref": "#/$defs/operand"},
                        "right": {"$ref": "#/$defs/operand"},
                        "tolerance": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "maximum": LINKED_COORDINATE_INVARIANT_MAX_TOLERANCE,
                        },
                    },
                    "required": ["id", "type", "left", "right", "tolerance"],
                },
            },
        },
        "required": [
            "version",
            "definitions",
            "animation",
            "coordinate_systems",
            "curves",
            "points",
            "links",
            "invariants",
        ],
    }


def linked_coordinate_ir_candidates_response_schema() -> dict[str, Any]:
    candidate = linked_coordinate_ir_response_schema()
    definitions = candidate.pop("$defs")
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": definitions,
        "properties": {
            "candidates": {
                "type": "array",
                "items": candidate,
                "minItems": 2,
                "maxItems": 2,
            }
        },
        "required": ["candidates"],
    }


def parse_linked_coordinate_ir(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text.startswith("{"):
        raise ValueError("missing_linked_coordinate_ir_object")
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"linked_coordinate_ir_json:{exc.msg}") from exc
    if text[end:].strip():
        raise ValueError("linked_coordinate_ir_trailing_content")
    if not isinstance(value, dict):
        raise ValueError("linked_coordinate_ir_must_be_object")
    return value


def parse_linked_coordinate_ir_candidates(raw_text: str) -> list[object]:
    envelope = parse_linked_coordinate_ir(raw_text)
    candidates = envelope.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("linked_coordinate_ir_candidates_must_contain_2_items")
    return candidates


def rank_linked_coordinate_ir_candidates(candidates: list[object], plan: dict[str, Any]) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        normalized = normalize_linked_coordinate_ir(candidate, plan)
        report = validate_linked_coordinate_ir(normalized, plan)
        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        reports.append(
            {
                "index": index,
                "eligible": report["ok"],
                "normalized": normalized != candidate,
                "error_count": len(report.get("errors", [])),
                "warning_count": len(report.get("warnings", [])),
                "chars": len(serialized),
                "fingerprint": sha256(serialized.encode("utf-8")).hexdigest(),
                "report": report,
                "ir": normalized,
            }
        )
    eligible = sorted(
        (item for item in reports if item["eligible"]),
        key=lambda item: (item["warning_count"], item["chars"], item["fingerprint"]),
    )
    repair_pool = sorted(
        reports,
        key=lambda item: (item["error_count"], item["warning_count"], item["chars"], item["fingerprint"]),
    )
    selected = eligible[0] if eligible else None
    repair = repair_pool[0] if repair_pool else None
    return {
        "ok": selected is not None,
        "selected_index": selected["index"] if selected else None,
        "selected_ir": selected["ir"] if selected else None,
        "repair_index": repair["index"] if repair else None,
        "repair_candidate": repair["ir"] if repair else None,
        "repair_report": repair["report"] if repair else None,
        "candidates": [
            {
                key: item[key]
                for key in (
                    "index",
                    "eligible",
                    "normalized",
                    "error_count",
                    "warning_count",
                    "chars",
                    "fingerprint",
                    "report",
                )
            }
            for item in reports
        ],
    }


def normalize_linked_coordinate_ir(ir: object, plan: dict[str, Any]) -> object:
    """Apply conservative, semantics-preserving fixes before hard validation."""
    if not isinstance(ir, dict):
        return ir
    normalized = deepcopy(ir)
    state_ranges = _state_ranges(plan)

    systems = normalized.get("coordinate_systems")
    if isinstance(systems, list):
        _apply_deterministic_coordinate_layout(systems)

    invariants = normalized.get("invariants")
    for invariant in invariants if isinstance(invariants, list) else []:
        if not isinstance(invariant, dict):
            continue
        tolerance = _number(invariant.get("tolerance"))
        if tolerance is not None and tolerance > LINKED_COORDINATE_INVARIANT_MAX_TOLERANCE:
            invariant["tolerance"] = LINKED_COORDINATE_INVARIANT_MAX_TOLERANCE

    curves = normalized.get("curves")
    for curve in curves if isinstance(curves, list) else []:
        if not isinstance(curve, dict):
            continue
        if "parameter_unit" not in curve:
            curve["parameter_unit"] = _infer_curve_parameter_unit(curve)
        if curve.get("reveal") is not None:
            continue
        domain = curve.get("domain")
        if not isinstance(domain, list) or len(domain) != 2:
            continue
        start = _number(domain[0])
        end = domain[1]
        if start is None or not isinstance(end, dict) or set(end) != {"state"}:
            continue
        variable = str(end["state"])
        state_range = state_ranges.get(variable)
        if state_range is None:
            continue
        minimum, _default, maximum = state_range
        if not math.isclose(start, minimum, rel_tol=0, abs_tol=1e-12) or maximum <= start:
            continue
        curve["domain"] = [start, maximum]
        curve["reveal"] = {
            "value": {"state": variable},
            "from": start,
            "to": maximum,
        }
    return normalized


def _apply_deterministic_coordinate_layout(systems: list[object]) -> None:
    count = len(systems)
    if not 1 <= count <= 4:
        return
    margin_x, margin_y, gap = 40.0, 40.0, 30.0
    columns = count if count <= 3 else 2
    rows = 1 if count <= 3 else 2
    width = (LINKED_COORDINATE_CANVAS_WIDTH - 2 * margin_x - gap * (columns - 1)) / columns
    height = (LINKED_COORDINATE_CANVAS_HEIGHT - 2 * margin_y - gap * (rows - 1)) / rows
    for index, system in enumerate(systems):
        if not isinstance(system, dict):
            continue
        column, row = index % columns, index // columns
        system.update(
            {
                "x": margin_x + column * (width + gap),
                "y": margin_y + row * (height + gap),
                "width": width,
                "height": height,
            }
        )


def _infer_curve_parameter_unit(curve: dict[str, Any]) -> str:
    parameter = str(curve.get("parameter") or "")
    expressions = (curve.get("x"), curve.get("y"))
    if parameter and any(_contains_converted_local(item, parameter) for item in expressions):
        return "degree"
    if parameter and any(_contains_trig_local(item, parameter) for item in expressions):
        return "radian"
    return "scalar"


def _contains_converted_local(node: object, parameter: str) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("op") == "deg_to_rad" and isinstance(node.get("args"), list):
        if any(isinstance(item, dict) and item == {"local": parameter} for item in node["args"]):
            return True
    return (
        any(_contains_converted_local(item, parameter) for item in node.get("args", []))
        if isinstance(node.get("args"), list)
        else False
    )


def _contains_trig_local(node: object, parameter: str) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("op") in {"sin", "cos", "tan"} and isinstance(node.get("args"), list):
        if any(_contains_local(item, parameter) for item in node["args"]):
            return True
    return (
        any(_contains_trig_local(item, parameter) for item in node.get("args", []))
        if isinstance(node.get("args"), list)
        else False
    )


def _contains_local(node: object, parameter: str) -> bool:
    if not isinstance(node, dict):
        return False
    if node == {"local": parameter}:
        return True
    return (
        any(_contains_local(item, parameter) for item in node.get("args", []))
        if isinstance(node.get("args"), list)
        else False
    )


def validate_linked_coordinate_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(ir, dict):
        return _report([_issue("invalid_linked_coordinate_ir", "联动坐标 IR 必须是 JSON 对象")], [])
    serialized = json.dumps(ir, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > LINKED_COORDINATE_IR_MAX_CHARS:
        errors.append(_issue("linked_coordinate_ir_too_long", "联动坐标 IR 超过长度上限"))
    if ir.get("version") != LINKED_COORDINATE_IR_VERSION:
        errors.append(_issue("unsupported_linked_coordinate_ir_version", "联动坐标 IR 版本不受支持"))

    state_ranges = _state_ranges(plan)
    state_units = _state_units(plan)
    definitions = ir.get("definitions") if isinstance(ir.get("definitions"), list) else []
    definition_map: dict[str, object] = {}
    for item in definitions:
        if not isinstance(item, dict) or not _identifier(item.get("name")):
            errors.append(_issue("invalid_definition", "definition 缺少合法名称"))
            continue
        name = str(item["name"])
        if name in definition_map:
            errors.append(_issue("duplicate_definition", f"definition 重复：{name}"))
        definition_map[name] = item.get("value")
    for name, expression in definition_map.items():
        _validate_expr(expression, state_ranges, definition_map, set(), errors, f"definition.{name}")
    _validate_degree_trig_states(ir, state_units, definition_map, errors)

    systems = _objects(ir.get("coordinate_systems"), 1, 4, "coordinate_systems", errors)
    curves = _objects(ir.get("curves"), 1, 8, "curves", errors)
    points = _objects(ir.get("points"), 1, 16, "points", errors)
    links = _objects(ir.get("links"), 0, 16, "links", errors)
    invariants = _objects(ir.get("invariants"), 1, 16, "invariants", errors)
    system_ids = _unique_ids(systems, "coordinate_system", errors)
    curve_ids = _unique_ids(curves, "curve", errors)
    point_ids = _unique_ids(points, "point", errors)
    _unique_ids(links, "link", errors)
    _unique_ids(invariants, "invariant", errors)

    animation = ir.get("animation") if isinstance(ir.get("animation"), dict) else {}
    animation_variable = str(animation.get("variable") or "")
    if animation_variable not in state_ranges:
        errors.append(_issue("invalid_animation_variable", "动画变量必须引用计划中的可调变量"))
    duration = _number(animation.get("duration"))
    if duration is None or not 0.5 <= duration <= 20:
        errors.append(_issue("invalid_animation_duration", "动画时长必须在 0.5~20 秒"))
    keyframes = animation.get("keyframes")
    if keyframes is not None:
        if not isinstance(keyframes, list) or not 2 <= len(keyframes) <= 8:
            errors.append(_issue("invalid_animation_keyframes", "动画关键帧必须包含 2~8 项"))
        else:
            previous = -1.0
            for index, keyframe in enumerate(keyframes):
                if not isinstance(keyframe, dict):
                    errors.append(_issue("invalid_animation_keyframe", "动画关键帧必须是对象", index=index))
                    continue
                progress = _number(keyframe.get("progress"))
                values = keyframe.get("state")
                if progress is None or not 0 <= progress <= 1 or progress <= previous:
                    errors.append(
                        _issue(
                            "invalid_animation_keyframe_progress",
                            "动画关键帧 progress 必须在 0~1 内严格递增",
                            index=index,
                        )
                    )
                else:
                    previous = progress
                if not isinstance(values, dict) or not values:
                    errors.append(_issue("invalid_animation_keyframe_state", "动画关键帧 state 不能为空", index=index))
                    continue
                for name, value in values.items():
                    number = _number(value)
                    if name not in state_ranges or number is None:
                        errors.append(
                            _issue(
                                "invalid_animation_keyframe_value",
                                "动画关键帧必须引用计划变量并提供有限数值",
                                index=index,
                                state=name,
                            )
                        )
                        continue
                    minimum, _default, maximum = state_ranges[name]
                    if not minimum <= number <= maximum:
                        errors.append(
                            _issue(
                                "animation_keyframe_out_of_range",
                                "动画关键帧数值超出计划变量范围",
                                index=index,
                                state=name,
                            )
                        )
            first_progress = _number(keyframes[0].get("progress")) if isinstance(keyframes[0], dict) else None
            last_progress = _number(keyframes[-1].get("progress")) if isinstance(keyframes[-1], dict) else None
            if first_progress != 0 or last_progress != 1:
                errors.append(_issue("animation_keyframes_must_span_timeline", "动画关键帧必须从 0 覆盖到 1"))

    for system in systems:
        if _requires_chinese_visible_label(system.get("label")):
            warnings.append(
                _issue(
                    "non_chinese_visible_label",
                    "坐标系说明标签建议使用简体中文；该质量提示不阻断 HTML 生成",
                    id=system.get("id"),
                    path="coordinate_systems.label",
                    value=system.get("label"),
                )
            )
        if any(_number(system.get(key)) is None for key in ("x", "y", "width", "height")):
            errors.append(_issue("invalid_coordinate_bounds", "坐标系边界必须为有限数值", id=system.get("id")))
            continue
        x, y = float(system["x"]), float(system["y"])
        width, height = float(system["width"]), float(system["height"])
        violations: list[str] = []
        if width < 120:
            violations.append(f"width={width:g} < 120")
        if height < 120:
            violations.append(f"height={height:g} < 120")
        if x < 0:
            violations.append(f"x={x:g} < 0")
        if y < 0:
            violations.append(f"y={y:g} < 0")
        if x + width > LINKED_COORDINATE_CANVAS_WIDTH:
            violations.append(f"x + width={x + width:g} > {LINKED_COORDINATE_CANVAS_WIDTH}")
        if y + height > LINKED_COORDINATE_CANVAS_HEIGHT:
            violations.append(f"y + height={y + height:g} > {LINKED_COORDINATE_CANVAS_HEIGHT}")
        if violations:
            errors.append(
                _issue(
                    "coordinate_bounds_outside_canvas",
                    "坐标系必须位于 960×560 画布内且尺寸充足",
                    id=system.get("id"),
                    bounds=[x, y, width, height],
                    violations=violations,
                )
            )
        _validate_pair(system.get("x_domain"), "x_domain", state_ranges, definition_map, set(), errors)
        _validate_pair(system.get("y_domain"), "y_domain", state_ranges, definition_map, set(), errors)

    for curve in curves:
        local = str(curve.get("parameter") or "")
        parameter_unit = curve.get("parameter_unit")
        if curve.get("system") not in system_ids or not _identifier(local):
            errors.append(_issue("invalid_curve_reference", "曲线必须引用坐标系并声明合法局部参数", id=curve.get("id")))
        if parameter_unit not in LINKED_COORDINATE_PARAMETER_UNITS:
            errors.append(
                _issue(
                    "invalid_curve_parameter_unit",
                    "曲线 parameter_unit 必须是 radian、degree 或 scalar",
                    id=curve.get("id"),
                )
            )
        samples = curve.get("samples")
        if not isinstance(samples, int) or not 48 <= samples <= 240:
            errors.append(_issue("invalid_curve_samples", "曲线采样数必须在 48~240", id=curve.get("id")))
        _validate_pair(curve.get("domain"), "curve_domain", state_ranges, definition_map, set(), errors)
        for key in ("x", "y"):
            _validate_expr(curve.get(key), state_ranges, definition_map, {local}, errors, f"curve.{key}")
            if parameter_unit == "degree":
                _validate_degree_trig_locals(curve.get(key), {local}, errors, f"curve.{curve.get('id')}.{key}")
        reveal = curve.get("reveal")
        if reveal is not None:
            if not isinstance(reveal, dict):
                errors.append(_issue("invalid_curve_reveal", "曲线 reveal 必须是对象", id=curve.get("id")))
            else:
                for key in ("value", "from", "to"):
                    _validate_expr(
                        reveal.get(key),
                        state_ranges,
                        definition_map,
                        set(),
                        errors,
                        f"curve.{curve.get('id')}.reveal.{key}",
                    )

    for point in points:
        if point.get("system") not in system_ids:
            errors.append(_issue("invalid_point_system", "动态点引用了不存在的坐标系", id=point.get("id")))
        for key in ("x", "y"):
            _validate_expr(point.get(key), state_ranges, definition_map, set(), errors, f"point.{key}")
    for link in links:
        if link.get("from") not in point_ids or link.get("to") not in point_ids:
            errors.append(_issue("invalid_link_reference", "投影连线端点必须引用动态点", id=link.get("id")))

    for key in ("from", "to"):
        _validate_expr(animation.get(key), state_ranges, definition_map, set(), errors, f"animation.{key}")

    for invariant in invariants:
        kind = invariant.get("type")
        if kind not in {"point_on_curve", "equal_value", "coincident"}:
            errors.append(_issue("invalid_invariant_type", "不变量类型不受支持", id=invariant.get("id")))
        tolerance = _number(invariant.get("tolerance"))
        if tolerance is None or tolerance <= 0 or tolerance > LINKED_COORDINATE_INVARIANT_MAX_TOLERANCE:
            errors.append(
                _issue(
                    "invalid_invariant_tolerance",
                    f"不变量 tolerance 必须在 0~{LINKED_COORDINATE_INVARIANT_MAX_TOLERANCE} 之间",
                    id=invariant.get("id"),
                )
            )
        for side in ("left", "right"):
            _validate_operand(invariant.get(side), point_ids, curve_ids, state_ranges, definition_map, errors)

    required_invariants = {
        str(item)
        for item in (
            (plan.get("representation_spec") or {}).get("required_invariants", [])
            if isinstance(plan.get("representation_spec"), dict)
            else []
        )
        if str(item) in {"point_on_curve", "equal_value", "coincident"}
    }
    provided_invariants = {str(item.get("type")) for item in invariants if isinstance(item, dict)}
    for missing in sorted(required_invariants - provided_invariants):
        errors.append(
            _issue(
                "missing_required_invariant",
                f"IR 未覆盖计划要求的不变量：{missing}",
                invariant=missing,
            )
        )

    if not errors:
        for state_name, state in _sample_states(state_ranges):
            try:
                evaluator = _Evaluator(state, definition_map)
                for definition_name in definition_map:
                    evaluator.eval({"var": definition_name})
                _validate_domains(systems, curves, evaluator)
                for invariant in invariants:
                    _check_invariant(invariant, points, curves, evaluator)
            except (ValueError, ArithmeticError, IndexError) as exc:
                errors.append(
                    _issue(
                        "linked_coordinate_ir_semantics",
                        f"{state_name} 状态不满足联动语义：{exc}",
                        state=state_name,
                    )
                )
    return _report(errors, warnings)


def _requires_chinese_visible_label(value: object) -> bool:
    """Detect English prose labels while leaving mathematical notation untouched."""
    text = str(value or "").strip()
    compact = re.sub(r"\s+", "", text)
    formula_only = compact == text and bool(re.search(r"[=()]", compact))
    return bool(text and not _CJK_RE.search(text) and _DESCRIPTIVE_LATIN_RE.search(text) and not formula_only)


def compile_linked_coordinate_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    normalized = normalize_linked_coordinate_ir(ir, plan)
    if not isinstance(normalized, dict):
        raise LinkedCoordinateIRValidationError(
            _report([_issue("invalid_linked_coordinate_ir", "联动坐标 IR 必须是 JSON 对象")], [])
        )
    report = validate_linked_coordinate_ir(normalized, plan)
    if not report["ok"]:
        raise LinkedCoordinateIRValidationError(report)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _validate_operand(
    operand: object,
    point_ids: set[str],
    curve_ids: set[str],
    states: dict[str, tuple[float, float, float]],
    definitions: dict[str, object],
    errors: list[dict[str, Any]],
) -> None:
    if not isinstance(operand, dict):
        errors.append(_issue("invalid_invariant_operand", "不变量操作数必须是对象"))
        return
    kind, ref = operand.get("kind"), operand.get("ref")
    if kind == "point" and ref not in point_ids:
        errors.append(_issue("invalid_invariant_point", "不变量引用了不存在的点", ref=ref))
    elif kind == "curve_sample" and ref not in curve_ids:
        errors.append(_issue("invalid_invariant_curve", "不变量引用了不存在的曲线", ref=ref))
    elif kind not in {"point", "curve_sample", "value"}:
        errors.append(_issue("invalid_invariant_operand_kind", "不变量操作数类型不受支持"))
    if operand.get("axis") not in {"x", "y", "both"}:
        errors.append(_issue("invalid_invariant_axis", "不变量 axis 不受支持"))
    _validate_expr(operand.get("at"), states, definitions, set(), errors, "invariant.at")
    _validate_expr(operand.get("value"), states, definitions, set(), errors, "invariant.value")


def _check_invariant(
    invariant: dict[str, Any],
    points: list[dict[str, Any]],
    curves: list[dict[str, Any]],
    evaluator: _Evaluator,
) -> None:
    point_map = {str(item["id"]): item for item in points}
    curve_map = {str(item["id"]): item for item in curves}
    left = _operand_value(invariant["left"], point_map, curve_map, evaluator)
    right = _operand_value(invariant["right"], point_map, curve_map, evaluator)
    tolerance = float(invariant.get("tolerance", 1e-6))
    if isinstance(left, tuple) and isinstance(right, tuple):
        distance = math.hypot(left[0] - right[0], left[1] - right[1])
    elif not isinstance(left, tuple) and not isinstance(right, tuple):
        distance = abs(float(left) - float(right))
    else:
        raise ValueError(f"invariant_operand_shape:{invariant.get('id')}")
    if not math.isfinite(distance) or distance > tolerance:
        raise ValueError(f"invariant_failed:{invariant.get('id')}:{distance:.6g}>{tolerance:.6g}")


def _operand_value(
    operand: dict[str, Any],
    points: dict[str, dict[str, Any]],
    curves: dict[str, dict[str, Any]],
    evaluator: _Evaluator,
) -> float | tuple[float, float]:
    kind = operand["kind"]
    if kind == "value":
        return evaluator.eval(operand["value"])
    if kind == "point":
        item = points[str(operand["ref"])]
        pair = (evaluator.eval(item["x"]), evaluator.eval(item["y"]))
    else:
        item = curves[str(operand["ref"])]
        local = {str(item["parameter"]): evaluator.eval(operand["at"])}
        pair = (evaluator.eval(item["x"], local), evaluator.eval(item["y"], local))
    axis = operand.get("axis")
    return pair[0] if axis == "x" else pair[1] if axis == "y" else pair


def _validate_domains(systems: list[dict[str, Any]], curves: list[dict[str, Any]], evaluator: _Evaluator) -> None:
    for item in systems:
        for key in ("x_domain", "y_domain"):
            pair = item[key]
            if evaluator.eval(pair[0]) >= evaluator.eval(pair[1]):
                raise ValueError(f"invalid_domain:{item.get('id')}:{key}")
    for curve in curves:
        start, end = (evaluator.eval(value) for value in curve["domain"])
        if start >= end:
            raise ValueError(f"invalid_curve_domain:{curve.get('id')}")
        reveal = curve.get("reveal")
        if isinstance(reveal, dict):
            reveal_from = evaluator.eval(reveal["from"])
            reveal_to = evaluator.eval(reveal["to"])
            evaluator.eval(reveal["value"])
            if reveal_from >= reveal_to:
                raise ValueError(f"invalid_curve_reveal:{curve.get('id')}")
        parameter = str(curve["parameter"])
        for value in (start, (start + end) / 2, end):
            evaluator.eval(curve["x"], {parameter: value})
            evaluator.eval(curve["y"], {parameter: value})


class _Evaluator:
    def __init__(self, state: dict[str, float], definitions: dict[str, object]) -> None:
        self.state = state
        self.definitions = definitions
        self.cache: dict[str, float] = {}
        self.resolving: set[str] = set()

    def eval(self, node: object, local: dict[str, float] | None = None) -> float:
        local = local or {}
        if isinstance(node, bool) or not isinstance(node, (int, float, dict)):
            raise ValueError("invalid_expression")
        if isinstance(node, (int, float)):
            return _finite(float(node))
        if set(node) == {"state"}:
            name = str(node["state"])
            if name not in self.state:
                raise ValueError(f"unknown_state:{name}")
            return _finite(self.state[name])
        if set(node) == {"local"}:
            name = str(node["local"])
            if name not in local:
                raise ValueError(f"unknown_local:{name}")
            return _finite(local[name])
        if set(node) == {"var"}:
            name = str(node["var"])
            if name in self.cache:
                return self.cache[name]
            if name not in self.definitions or name in self.resolving:
                raise ValueError(f"invalid_definition_reference:{name}")
            self.resolving.add(name)
            value = self.eval(self.definitions[name], local)
            self.resolving.remove(name)
            self.cache[name] = value
            return value
        if set(node) != {"op", "args"} or node.get("op") not in _OPS or not isinstance(node.get("args"), list):
            raise ValueError("invalid_expression")
        values = [self.eval(item, local) for item in node["args"]]
        return _finite(_apply_op(str(node["op"]), values))


def _apply_op(name: str, values: list[float]) -> float:
    if not values:
        raise ValueError("empty_operator")
    if name == "add":
        return sum(values)
    if name == "sub":
        return values[0] - sum(values[1:])
    if name == "mul":
        return math.prod(values)
    if name == "div":
        result = values[0]
        for value in values[1:]:
            if value == 0:
                raise ValueError("division_by_zero")
            result /= value
        return result
    if name == "pow":
        return values[0] ** values[1]
    if name == "mod":
        return values[0] % values[1]
    if name == "min":
        return min(values)
    if name == "max":
        return max(values)
    if name == "clamp":
        return max(values[1], min(values[2], values[0]))
    if name == "neg":
        return -values[0]
    if name == "abs":
        return abs(values[0])
    if name == "sqrt":
        return math.sqrt(values[0])
    if name == "sin":
        return math.sin(values[0])
    if name == "cos":
        return math.cos(values[0])
    if name == "tan":
        return math.tan(values[0])
    if name == "asin":
        return math.asin(values[0])
    if name == "acos":
        return math.acos(values[0])
    if name == "atan":
        return math.atan(values[0])
    if name == "atan2":
        return math.atan2(values[0], values[1])
    if name == "exp":
        return math.exp(values[0])
    if name == "log":
        return math.log(values[0])
    if name == "deg_to_rad":
        return math.radians(values[0])
    raise ValueError(f"unknown_operator:{name}")


def _validate_pair(
    value: object,
    label: str,
    states: dict[str, tuple[float, float, float]],
    definitions: dict[str, object],
    locals_: set[str],
    errors: list[dict[str, Any]],
) -> None:
    if not isinstance(value, list) or len(value) != 2:
        errors.append(_issue("invalid_expression_pair", f"{label} 必须包含两个表达式"))
        return
    for item in value:
        _validate_expr(item, states, definitions, locals_, errors, label)


def _validate_expr(
    node: object,
    states: dict[str, tuple[float, float, float]],
    definitions: dict[str, object],
    locals_: set[str],
    errors: list[dict[str, Any]],
    label: str,
) -> None:
    if isinstance(node, bool):
        errors.append(_issue("invalid_expression", f"{label} 不允许布尔值"))
        return
    if isinstance(node, (int, float)):
        if not math.isfinite(float(node)):
            errors.append(_issue("non_finite_expression", f"{label} 包含非有限数值"))
        return
    if not isinstance(node, dict):
        errors.append(_issue("invalid_expression", f"{label} 表达式无效"))
        return
    if set(node) == {"state"} and node.get("state") in states:
        return
    if set(node) == {"var"} and node.get("var") in definitions:
        return
    if set(node) == {"local"} and node.get("local") in locals_:
        return
    if (
        set(node) == {"op", "args"}
        and node.get("op") in _OPS
        and isinstance(node.get("args"), list)
        and _valid_arity(str(node.get("op")), len(node["args"]))
    ):
        for item in node["args"]:
            _validate_expr(item, states, definitions, locals_, errors, label)
        return
    errors.append(_issue("invalid_expression_reference", f"{label} 含未知引用或操作符"))


def _valid_arity(operator: str, count: int) -> bool:
    if operator in {"neg", "abs", "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "exp", "log", "deg_to_rad"}:
        return count == 1
    if operator in {"pow", "mod", "atan2"}:
        return count == 2
    if operator == "clamp":
        return count == 3
    return 1 <= count <= 12


def _state_ranges(plan: dict[str, Any]) -> dict[str, tuple[float, float, float]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    result: dict[str, tuple[float, float, float]] = {}
    for item in spec.get("variables", []):
        if not isinstance(item, dict) or item.get("computed") or not _identifier(item.get("name")):
            continue
        minimum = _number(item.get("min"))
        maximum = _number(item.get("max"))
        default = _number(item.get("default"))
        if minimum is None or maximum is None or default is None or minimum > maximum:
            continue
        result[str(item["name"])] = (minimum, min(max(default, minimum), maximum), maximum)
    return result


def _state_units(plan: dict[str, Any]) -> dict[str, str]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    return {
        str(item["name"]): str(item.get("unit") or "").strip().lower()
        for item in spec.get("variables", [])
        if isinstance(item, dict) and item.get("name") and not item.get("computed")
    }


def _validate_degree_trig_states(
    root: object,
    state_units: dict[str, str],
    definitions: dict[str, object],
    errors: list[dict[str, Any]],
) -> None:
    emitted: set[str] = set()

    def visit(node: object, path: str) -> None:
        if isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, f"{path}[{index}]")
            return
        if not isinstance(node, dict):
            return
        if node.get("op") in {"sin", "cos", "tan"} and isinstance(node.get("args"), list):
            if any(_contains_unconverted_degree_state(item, state_units, definitions, set()) for item in node["args"]):
                key = f"{path}:{node.get('op')}"
                if key not in emitted:
                    emitted.add(key)
                    errors.append(
                        _issue(
                            "degree_trig_requires_conversion",
                            f"{path} 的 {node.get('op')} 接收了角度制状态；必须先使用 deg_to_rad",
                            path=path,
                        )
                    )
        for key, value in node.items():
            visit(value, f"{path}.{key}" if path else str(key))

    visit(root, "ir")


def _contains_unconverted_degree_state(
    node: object,
    state_units: dict[str, str],
    definitions: dict[str, object],
    resolving: set[str],
) -> bool:
    if not isinstance(node, dict):
        return False
    if set(node) == {"state"}:
        return _is_degree_unit(state_units.get(str(node["state"]), ""))
    if set(node) == {"var"}:
        name = str(node["var"])
        if name in resolving or name not in definitions:
            return False
        return _contains_unconverted_degree_state(definitions[name], state_units, definitions, {*resolving, name})
    if node.get("op") == "deg_to_rad":
        return False
    return (
        any(
            _contains_unconverted_degree_state(item, state_units, definitions, resolving)
            for item in node.get("args", [])
        )
        if isinstance(node.get("args"), list)
        else False
    )


def _validate_degree_trig_locals(
    root: object, degree_locals: set[str], errors: list[dict[str, Any]], path: str
) -> None:
    if isinstance(root, list):
        for index, item in enumerate(root):
            _validate_degree_trig_locals(item, degree_locals, errors, f"{path}[{index}]")
        return
    if not isinstance(root, dict):
        return
    if root.get("op") in {"sin", "cos", "tan"} and isinstance(root.get("args"), list):
        if any(_contains_unconverted_degree_local(item, degree_locals) for item in root["args"]):
            errors.append(
                _issue(
                    "degree_trig_requires_conversion",
                    f"{path} 的局部角度参数必须先使用 deg_to_rad",
                    path=path,
                )
            )
    for index, item in enumerate(root.get("args", [])):
        _validate_degree_trig_locals(item, degree_locals, errors, f"{path}.args[{index}]")


def _contains_unconverted_degree_local(node: object, degree_locals: set[str]) -> bool:
    if not isinstance(node, dict):
        return False
    if set(node) == {"local"}:
        return str(node["local"]) in degree_locals
    if node.get("op") == "deg_to_rad":
        return False
    return (
        any(_contains_unconverted_degree_local(item, degree_locals) for item in node.get("args", []))
        if isinstance(node.get("args"), list)
        else False
    )


def _is_degree_unit(unit: str) -> bool:
    return unit.strip().lower() in {"°", "deg", "degree", "degrees", "度"}


def _sample_states(ranges: dict[str, tuple[float, float, float]]) -> list[tuple[str, dict[str, float]]]:
    baseline = {name: values[1] for name, values in ranges.items()}
    candidates: list[tuple[str, dict[str, float]]] = [
        (label, {name: values[index] for name, values in ranges.items()})
        for index, label in enumerate(("minimum", "default", "maximum"))
    ]
    for name, (minimum, _default, maximum) in ranges.items():
        span = maximum - minimum
        for label, ratio in (("quarter", 0.25), ("midpoint", 0.5), ("three_quarters", 0.75)):
            state = dict(baseline)
            state[name] = minimum + span * ratio
            candidates.append((f"{name}:{label}", state))

    result: list[tuple[str, dict[str, float]]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for label, state in candidates:
        fingerprint = tuple(sorted(state.items()))
        if fingerprint not in seen:
            seen.add(fingerprint)
            result.append((label, state))
    return result


def _objects(
    value: object, minimum: int, maximum: int, label: str, errors: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or not minimum <= len(value) <= maximum
        or not all(isinstance(item, dict) for item in value)
    ):
        errors.append(_issue("invalid_collection", f"{label} 数量或结构无效"))
        return []
    return value


def _unique_ids(items: list[dict[str, Any]], label: str, errors: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for item in items:
        value = item.get("id")
        if not _identifier(value) or value in result:
            errors.append(_issue("invalid_or_duplicate_id", f"{label} id 缺失或重复", id=value))
            continue
        result.add(str(value))
    return result


def _identifier(value: object) -> bool:
    text = str(value or "")
    return bool(text) and len(text) <= 64 and all(char.isalnum() or char in "_-" for char in text)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("non_finite_result")
    return value


def _issue(kind: str, message: str, **details: Any) -> dict[str, Any]:
    return {"type": kind, "message": message, **details}


def _report(errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "ok",
        "summary": "联动坐标 IR 契约检查完成" if not errors else f"联动坐标 IR 存在 {len(errors)} 个硬错误",
        "errors": errors,
        "warnings": warnings,
    }
