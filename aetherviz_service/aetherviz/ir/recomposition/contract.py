"""Validated geometry IR and restricted expression DSL for recomposition scenes."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

GEOMETRY_IR_VERSION = "aetherviz.geometry-ir.v1"
GEOMETRY_IR_MAX_CHARS = 10_000
MAX_PIECE_TEMPLATES = 16
MAX_EXPANDED_PIECES = 80
MAX_EXPRESSION_DEPTH = 12
MAX_EXPRESSION_NODES = 800

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
_ALLOWED_TAGS = {"path", "polygon", "polyline", "rect", "circle", "ellipse", "line"}
_COMMON_ATTRS = {"fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "class"}
_TAG_ATTRS = {
    "path": {"d"},
    "polygon": {"points"},
    "polyline": {"points"},
    "rect": {"x", "y", "width", "height", "rx", "ry"},
    "circle": {"cx", "cy", "r"},
    "ellipse": {"cx", "cy", "rx", "ry"},
    "line": {"x1", "y1", "x2", "y2"},
}
_REQUIRED_ATTRS = {
    "path": {"d"},
    "polygon": {"points"},
    "polyline": {"points"},
    "rect": {"width", "height"},
    "circle": {"r"},
    "ellipse": {"rx", "ry"},
    "line": {"x1", "y1", "x2", "y2"},
}
_POSITIVE_ATTRS = {"width", "height", "r", "rx", "ry"}
_TRANSFORM_KEYS = {"x", "y", "rotation", "scale", "opacity"}
_UNARY_OPS = {
    "neg",
    "abs",
    "sqrt",
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "round",
    "floor",
    "ceil",
    "rad_to_deg",
    "deg_to_rad",
}
_BINARY_OPS = {"pow", "mod", "atan2", "hypot", "eq", "ne", "lt", "lte", "gt", "gte"}
_FOLD_OPS = {"sub", "div"}
_TERNARY_OPS = {"clamp", "if"}
_VARIADIC_OPS = {"add", "mul", "min", "max", "concat"}
_SPECIAL_OPS = {"fixed", "points", "sector_path"}
_ALLOWED_OPS = _UNARY_OPS | _BINARY_OPS | _FOLD_OPS | _TERNARY_OPS | _VARIADIC_OPS | _SPECIAL_OPS


def geometry_ir_response_schema() -> dict[str, Any]:
    """Strict transport schema; list pairs are normalized into internal maps."""

    def operator_variant(operators: set[str], minimum: int, maximum: int) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": sorted(operators)},
                "args": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/expression"},
                    "minItems": minimum,
                    "maxItems": maximum,
                },
            },
            "required": ["op", "args"],
            "additionalProperties": False,
        }

    expression: dict[str, Any] = {
        "anyOf": [
            {"type": "number"},
            {"type": "string"},
            {"type": "array", "items": {"$ref": "#/$defs/expression"}, "maxItems": 64},
            {
                "type": "object",
                "properties": {"state": {"type": "string"}},
                "required": ["state"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"var": {"type": "string"}},
                "required": ["var"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"local": {"type": "string"}},
                "required": ["local"],
                "additionalProperties": False,
            },
            operator_variant(_UNARY_OPS, 1, 1),
            operator_variant(_BINARY_OPS, 2, 2),
            operator_variant(_FOLD_OPS, 2, 16),
            operator_variant(_TERNARY_OPS, 3, 3),
            operator_variant(_VARIADIC_OPS, 1, 16),
            operator_variant({"fixed"}, 2, 2),
            operator_variant({"points"}, 1, 40),
            operator_variant({"sector_path"}, 5, 6),
        ]
    }
    transform = {
        "type": "object",
        "properties": {name: {"$ref": "#/$defs/expression"} for name in sorted(_TRANSFORM_KEYS)},
        "required": sorted(_TRANSFORM_KEYS),
        "additionalProperties": False,
    }
    keyframe = {
        "type": "object",
        "properties": {"at": {"type": "number"}, **transform["properties"]},
        "required": ["at", *sorted(_TRANSFORM_KEYS)],
        "additionalProperties": False,
    }
    edge_reference_properties = {
        "piece_id": {"type": "string"},
        "edge": {"type": "integer", "minimum": 0, "maximum": 63},
        "to_piece_id": {"type": "string"},
        "to_edge": {"type": "integer", "minimum": 0, "maximum": 63},
    }
    construction_constraint = {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["attach_edge"]},
                    **edge_reference_properties,
                    "reverse": {"type": "boolean"},
                },
                "required": ["type", *edge_reference_properties, "reverse"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["coincident_vertex"]},
                    "piece_id": {"type": "string"},
                    "vertex": {"type": "integer", "minimum": 0, "maximum": 63},
                    "to_piece_id": {"type": "string"},
                    "to_vertex": {"type": "integer", "minimum": 0, "maximum": 63},
                },
                "required": ["type", "piece_id", "vertex", "to_piece_id", "to_vertex"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["parallel_edge", "perpendicular_edge"]},
                    **edge_reference_properties,
                },
                "required": ["type", *edge_reference_properties],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["rigid_transform"]},
                    "piece_id": {"type": "string"},
                    "transform": {"$ref": "#/$defs/transform"},
                },
                "required": ["type", "piece_id", "transform"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["inside_target"]},
                    "piece_id": {"type": "string"},
                },
                "required": ["type", "piece_id"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["cover_target"]},
                    "piece_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 16,
                    },
                    "min_coverage_ratio": {"type": "number", "minimum": 0.5, "maximum": 1},
                },
                "required": ["type", "piece_ids", "min_coverage_ratio"],
                "additionalProperties": False,
            },
        ]
    }
    return {
        "type": "object",
        "properties": {
            "version": {"type": "string", "enum": [GEOMETRY_IR_VERSION]},
            "definitions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "value": {"$ref": "#/$defs/expression"}},
                    "required": ["name", "value"],
                    "additionalProperties": False,
                },
                "maxItems": 32,
            },
            "pieces": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "repeat": {
                            "anyOf": [
                                {"type": "null"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "count": {"$ref": "#/$defs/expression"},
                                        "index": {"type": "string"},
                                    },
                                    "required": ["count", "index"],
                                    "additionalProperties": False,
                                },
                            ]
                        },
                        "id": {"$ref": "#/$defs/expression"},
                        "tag": {"type": "string", "enum": sorted(_ALLOWED_TAGS)},
                        "attrs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "enum": sorted(_COMMON_ATTRS | set().union(*_TAG_ATTRS.values())),
                                    },
                                    "value": {"$ref": "#/$defs/expression"},
                                },
                                "required": ["name", "value"],
                                "additionalProperties": False,
                            },
                            "minItems": 1,
                        },
                        "source": {"$ref": "#/$defs/transform"},
                        "target": {"$ref": "#/$defs/transform"},
                        "keyframes": {"type": "array", "items": {"$ref": "#/$defs/keyframe"}, "maxItems": 5},
                    },
                    "required": ["repeat", "id", "tag", "attrs", "source", "target", "keyframes"],
                    "additionalProperties": False,
                },
                "minItems": 1,
                "maxItems": MAX_PIECE_TEMPLATES,
            },
            "frames": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stage_id": {"type": "string"},
                        "at": {"type": "number"},
                        "caption": {"type": "string"},
                        "formula": {"type": "string"},
                        "step": {"type": "integer"},
                    },
                    "required": ["stage_id", "at", "caption", "formula", "step"],
                    "additionalProperties": False,
                },
                "minItems": 3,
                "maxItems": 5,
            },
            "construction": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "target_boundary": {
                                "anyOf": [
                                    {"type": "null"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            name: {"$ref": "#/$defs/expression"}
                                            for name in ("x", "y", "width", "height")
                                        },
                                        "required": ["x", "y", "width", "height"],
                                        "additionalProperties": False,
                                    },
                                ]
                            },
                            "constraints": {
                                "type": "array",
                                "items": {"$ref": "#/$defs/construction_constraint"},
                                "minItems": 1,
                                "maxItems": 24,
                            }
                        },
                        "required": ["target_boundary", "constraints"],
                        "additionalProperties": False,
                    },
                ]
            },
        },
        "required": ["version", "definitions", "pieces", "frames", "construction"],
        "additionalProperties": False,
        "$defs": {
            "expression": expression,
            "transform": transform,
            "keyframe": keyframe,
            "construction_constraint": construction_constraint,
        },
    }


def geometry_ir_candidates_response_schema() -> dict[str, Any]:
    """Strict response envelope for three independently generated IR candidates."""
    schema = geometry_ir_response_schema()
    candidate = {key: value for key, value in schema.items() if key != "$defs"}
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": candidate,
                "minItems": 2,
                "maxItems": 3,
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
        "$defs": schema["$defs"],
    }


@dataclass(frozen=True)
class GeometryIRValidationError(ValueError):
    report: dict[str, Any]

    def __str__(self) -> str:
        return ",".join(str(item.get("type")) for item in self.report.get("errors", []))


def parse_geometry_ir(raw_text: str) -> dict[str, Any]:
    """Extract one JSON object; JavaScript and trailing prose are never accepted."""
    text = (raw_text or "").strip()
    fence = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        raise ValueError("missing_geometry_ir_object")
    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"geometry_ir_json:{exc.msg}") from exc
    if text[end:].strip():
        raise ValueError("geometry_ir_trailing_content")
    if not isinstance(value, dict):
        raise ValueError("geometry_ir_must_be_object")
    return value


def parse_geometry_ir_candidates(raw_text: str) -> list[object]:
    """Parse a bounded candidate envelope without silently accepting one candidate."""
    envelope = parse_geometry_ir(raw_text)
    candidates = envelope.get("candidates")
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 3:
        raise ValueError("geometry_ir_candidates_must_contain_2_to_3_items")
    return candidates


def extract_geometry_ir_from_scene_source(source: str) -> dict[str, Any]:
    marker = "const sceneIR="
    start = (source or "").find(marker)
    if start < 0:
        raise ValueError("missing_compiled_geometry_ir")
    value, _ = json.JSONDecoder().raw_decode(source[start + len(marker) :])
    if not isinstance(value, dict):
        raise ValueError("compiled_geometry_ir_must_be_object")
    return value


def normalize_geometry_ir(ir: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Apply only unambiguous syntax normalization; never infer topic geometry."""
    normalized = json.loads(json.dumps(ir, ensure_ascii=False))
    if isinstance(normalized.get("definitions"), list):
        normalized["definitions"] = {
            str(item.get("name")): item.get("value")
            for item in normalized["definitions"]
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
    requirements = _stage_requirements(plan)
    frames = normalized.get("frames")
    if isinstance(frames, list) and requirements and len(frames) == len(requirements):
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict):
                continue
            # Candidate ingest: align display frames to plan stage_requirements by index
            # so timeline/id mismatches do not become teaching hard failures.
            requirement = requirements[index]
            frame["stage_id"] = requirement["id"]
            frame["at"] = requirement["at"]
    required_ats = [
        float(stage["at"])
        for stage in requirements
        if isinstance(stage, dict) and _finite_float(stage.get("at")) is not None
    ]
    for piece in normalized.get("pieces", []) if isinstance(normalized.get("pieces"), list) else []:
        if not isinstance(piece, dict):
            continue
        repeat = piece.get("repeat")
        piece_id = piece.get("id")
        if (
            isinstance(repeat, dict)
            and isinstance(piece_id, str)
            and piece_id
            and _IDENTIFIER_RE.fullmatch(str(repeat.get("index", "")))
        ):
            # A literal id inside repeat necessarily expands to duplicates. Preserve
            # the model-provided prefix while making each expanded piece identifiable.
            piece["id"] = {
                "op": "concat",
                "args": [f"{piece_id}-", {"local": str(repeat["index"])}],
            }
        if isinstance(piece.get("attrs"), list):
            piece["attrs"] = {
                str(item.get("name")): item.get("value")
                for item in piece["attrs"]
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            }
        if piece.get("repeat") is None:
            piece.pop("repeat", None)
        if piece.get("keyframes") == []:
            piece.pop("keyframes", None)
        elif isinstance(piece.get("keyframes"), list):
            keyframes = [frame for frame in piece["keyframes"] if isinstance(frame, dict)]
            if keyframes and all(_finite_float(frame.get("at")) is not None for frame in keyframes):
                keyframes.sort(key=lambda frame: float(frame["at"]))
                source = piece.get("source") if isinstance(piece.get("source"), dict) else {}
                target = piece.get("target") if isinstance(piece.get("target"), dict) else {}
                if float(keyframes[0]["at"]) != 0:
                    keyframes.insert(0, {"at": 0, **source})
                else:
                    keyframes[0] = {**source, **keyframes[0], "at": 0}
                if float(keyframes[-1]["at"]) != 1:
                    keyframes.append({"at": 1, **target})
                else:
                    keyframes[-1] = {**target, **keyframes[-1], "at": 1}
                # When the model already emitted one keyframe per planned stage, snap
                # ats onto the plan timeline so intermediate evidence is checked at the
                # intended teaching moments instead of near-miss neighboring times.
                if required_ats and len(keyframes) == len(required_ats):
                    for frame, at in zip(keyframes, required_ats, strict=True):
                        frame["at"] = at
                piece["keyframes"] = keyframes
    definitions = normalized.get("definitions") if isinstance(normalized.get("definitions"), dict) else {}
    state_names = _plan_state_names(plan)

    def visit(value: object) -> object:
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        if len(value) == 1:
            shorthand, operand = next(iter(value.items()))
            if shorthand in _UNARY_OPS:
                return {"op": shorthand, "args": [visit(operand)]}
        if set(value) == {"var"} and value.get("var") in state_names and value.get("var") not in definitions:
            return {"state": value["var"]}
        result = {key: visit(item) for key, item in value.items()}
        aliases = {
            "rad2deg": "rad_to_deg",
            "deg2rad": "deg_to_rad",
            "arctan": "atan",
            "arctan2": "atan2",
            "Math.atan": "atan",
            "Math.atan2": "atan2",
        }
        if set(result) == {"op", "args"} and result.get("op") in aliases:
            result["op"] = aliases[str(result["op"])]
        if set(result) == {"op", "args"} and not isinstance(result.get("args"), list):
            result["args"] = [result["args"]]
        return result

    result = visit(normalized)
    return result if isinstance(result, dict) else normalized


def validate_geometry_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(ir, dict):
        return _report([_issue("invalid_geometry_ir", "几何 IR 必须是 JSON 对象")], [])
    serialized = json.dumps(ir, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > GEOMETRY_IR_MAX_CHARS:
        errors.append(_issue("geometry_ir_too_long", "几何 IR 超过长度上限", chars=len(serialized)))
    if ir.get("version") != GEOMETRY_IR_VERSION:
        errors.append(_issue("unsupported_geometry_ir_version", "几何 IR 版本不受支持"))
    if ir.get("construction") is not None:
        errors.append(
            _issue(
                "unmaterialized_target_construction",
                "construction 约束必须先由服务端求解为 target transform",
            )
        )

    definitions = ir.get("definitions", {})
    if not isinstance(definitions, dict) or len(definitions) > 32:
        errors.append(_issue("invalid_definitions", "definitions 必须是最多 32 项的对象"))
        definitions = {}
    definition_names = set(definitions)
    if any(not _IDENTIFIER_RE.fullmatch(str(name)) for name in definition_names):
        errors.append(_issue("invalid_definition_name", "definitions 名称不合法"))

    state_names = _plan_state_names(plan)
    pieces = ir.get("pieces")
    definition_locals = {
        str(piece["repeat"]["index"])
        for piece in (pieces if isinstance(pieces, list) else [])
        if isinstance(piece, dict)
        and isinstance(piece.get("repeat"), dict)
        and _IDENTIFIER_RE.fullmatch(str(piece["repeat"].get("index", "")))
    }
    budget = [0]
    for name, expression in definitions.items():
        _validate_expression(
            expression,
            path=f"definitions.{name}",
            state_names=state_names,
            definition_names=definition_names,
            local_names=definition_locals,
            depth=0,
            budget=budget,
            errors=errors,
        )

    if not isinstance(pieces, list) or not 1 <= len(pieces) <= MAX_PIECE_TEMPLATES:
        errors.append(_issue("invalid_piece_templates", "pieces 必须包含 1~16 个图元模板"))
        pieces = []
    for index, piece in enumerate(pieces):
        _validate_piece_template(
            piece,
            index=index,
            state_names=state_names,
            definitions=definitions,
            definition_names=definition_names,
            require_index_independent_geometry=_piece_congruence_required(plan),
            budget=budget,
            errors=errors,
        )

    frames = ir.get("frames")
    if not isinstance(frames, list) or not 3 <= len(frames) <= 5:
        errors.append(_issue("invalid_display_frames", "frames 必须包含 3~5 个教学帧"))
    else:
        previous_at = -1.0
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict):
                errors.append(_issue("invalid_display_frame", "教学帧必须是对象", index=index))
                continue
            at = _finite_float(frame.get("at"))
            step = frame.get("step")
            if at is None or not 0 <= at <= 1 or at <= previous_at:
                errors.append(_issue("invalid_frame_progress", "教学帧 at 必须在 0~1 内严格递增", index=index))
            else:
                previous_at = at
            stage_id = frame.get("stage_id")
            if not isinstance(stage_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", stage_id):
                errors.append(_issue("invalid_frame_stage_id", "教学帧 stage_id 不合法", index=index))
            if not isinstance(step, int) or isinstance(step, bool) or step < 0 or step > 9:
                errors.append(_issue("invalid_frame_step", "教学帧 step 必须是非负整数", index=index))
            for key in ("caption", "formula"):
                value = frame.get(key, "")
                if not isinstance(value, str) or len(value) > 300:
                    errors.append(_issue("invalid_frame_text", f"教学帧 {key} 不合法", index=index))

    if budget[0] > MAX_EXPRESSION_NODES:
        errors.append(
            _issue(
                "geometry_ir_expression_budget",
                "表达式节点数量超过上限",
                nodes=budget[0],
            )
        )
    if not errors:
        for label, state in _sample_states(plan):
            try:
                expanded = _expand_geometry(ir, state)
                _validate_expanded_geometry(expanded)
            except ValueError as exc:
                errors.append(_issue("geometry_ir_semantics", f"{label} 状态无效：{exc}", state=label))
    return _report(errors, warnings)


def compile_geometry_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    report = validate_geometry_ir(ir, plan)
    if not report["ok"]:
        raise GeometryIRValidationError(report)
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    topology = list(
        dict.fromkeys(
            [
                *[str(name) for name in spec.get("topology_variables", []) if str(name)],
                *_repeat_count_state_variables(ir),
            ]
        )
    )
    ir_json = json.dumps(ir, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    topology_json = json.dumps(topology, ensure_ascii=False, separators=(",", ":"))
    return f"const sceneIR={ir_json};\n" + _COMPILED_RUNTIME.replace("__TOPOLOGY__", topology_json)


def _repeat_count_state_variables(ir: dict[str, Any]) -> list[str]:
    """Return state variables that can alter repeat expansion and therefore identity."""
    definitions = ir.get("definitions") if isinstance(ir.get("definitions"), dict) else {}
    found: list[str] = []

    def visit(value: object, resolving: frozenset[str] = frozenset()) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, resolving)
            return
        if not isinstance(value, dict):
            return
        if set(value) == {"state"}:
            name = str(value.get("state") or "")
            if name and name not in found:
                found.append(name)
            return
        if set(value) == {"var"}:
            name = str(value.get("var") or "")
            if name in definitions and name not in resolving:
                visit(definitions[name], resolving | {name})
            return
        for item in value.values():
            visit(item, resolving)

    pieces = ir.get("pieces") if isinstance(ir.get("pieces"), list) else []
    for piece in pieces:
        repeat = piece.get("repeat") if isinstance(piece, dict) else None
        if isinstance(repeat, dict):
            visit(repeat.get("count"))
    return found


def build_deterministic_geometry_ir(plan: dict[str, Any]) -> dict[str, Any]:
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    topology = next((str(name) for name in spec.get("topology_variables", []) if str(name)), "")
    geometry = next((str(name) for name in spec.get("geometry_variables", []) if str(name)), "")
    count_expr: object = (
        {"op": "clamp", "args": [{"op": "round", "args": [{"state": topology}]}, 3, 20]} if topology else 6
    )
    scale_expr: object = (
        {
            "op": "clamp",
            "args": [{"op": "add", "args": [0.7, {"op": "mul", "args": [{"state": geometry}, 0.04]}]}, 0.55, 1.35],
        }
        if geometry
        else 1
    )
    source = {
        "x": {
            "op": "add",
            "args": [
                180,
                {
                    "op": "mul",
                    "args": [
                        {"op": "mod", "args": [{"local": "i"}, 5]},
                        {"op": "mul", "args": [{"var": "tileSize"}, 1.18]},
                    ],
                },
            ],
        },
        "y": {
            "op": "add",
            "args": [
                90,
                {
                    "op": "mul",
                    "args": [
                        {"op": "floor", "args": [{"op": "div", "args": [{"local": "i"}, 5]}]},
                        {"op": "mul", "args": [{"var": "tileSize"}, 1.18]},
                    ],
                },
            ],
        },
        "rotation": 0,
        "scale": {"var": "shapeScale"},
        "opacity": 1,
    }
    target = {
        "x": {
            "op": "add",
            "args": [
                {"var": "targetOriginX"},
                {
                    "op": "mul",
                    "args": [
                        {
                            "op": "add",
                            "args": [
                                {"op": "floor", "args": [{"op": "div", "args": [{"local": "i"}, 2]}]},
                                {"op": "mod", "args": [{"local": "i"}, 2]},
                            ],
                        },
                        {"var": "tileSize"},
                    ],
                },
            ],
        },
        "y": {
            "op": "add",
            "args": [
                330,
                {
                    "op": "mul",
                    "args": [
                        {"op": "mod", "args": [{"local": "i"}, 2]},
                        {"var": "tileSize"},
                    ],
                },
            ],
        },
        "rotation": {"op": "mul", "args": [{"op": "mod", "args": [{"local": "i"}, 2]}, 180]},
        "scale": {"var": "shapeScale"},
        "opacity": 1,
    }
    stages = _stage_requirements(plan)
    keyframes = []
    frames = []
    for index, stage in enumerate(stages):
        role = stage["role"]
        at = stage["at"]
        if role == "source":
            transform = source
            formula = "源状态：图形块身份保持不变"
        elif role == "target":
            transform = target
            formula = "源/目标图形块集合相同"
        else:
            transform = {
                "x": {"op": "add", "args": [source["x"], 70 + index * 28]},
                "y": {"op": "sub", "args": [source["y"], 45 + index * 12]},
                "rotation": 30 + index * 25,
                "scale": {"var": "shapeScale"},
                "opacity": 1,
            }
            formula = "中间阶段：图形块集合与度量保持不变"
        keyframes.append({"at": at, **transform})
        frames.append(
            {
                "stage_id": stage["id"],
                "at": at,
                "caption": stage["intent"],
                "formula": formula,
                "step": index,
            }
        )
    return {
        "version": GEOMETRY_IR_VERSION,
        "definitions": {
            "count": count_expr,
            "shapeScale": scale_expr,
            "tileBase": {
                "op": "clamp",
                "args": [
                    {
                        "op": "div",
                        "args": [
                            520,
                            {
                                "op": "add",
                                "args": [{"op": "floor", "args": [{"op": "div", "args": [{"var": "count"}, 2]}]}, 1],
                            },
                        ],
                    },
                    44,
                    96,
                ],
            },
            "tileSize": {"op": "mul", "args": [{"var": "tileBase"}, {"var": "shapeScale"}]},
            "targetWidth": {
                "op": "mul",
                "args": [
                    {
                        "op": "add",
                        "args": [{"op": "floor", "args": [{"op": "div", "args": [{"var": "count"}, 2]}]}, 1],
                    },
                    {"var": "tileSize"},
                ],
            },
            "targetOriginX": {"op": "sub", "args": [480, {"op": "div", "args": [{"var": "targetWidth"}, 2]}]},
        },
        "pieces": [
            {
                "repeat": {"count": {"var": "count"}, "index": "i"},
                "id": {"op": "concat", "args": ["piece-", {"local": "i"}]},
                "tag": "polygon",
                "attrs": {
                    "points": {
                        "op": "points",
                        "args": [[0, 0], [{"var": "tileBase"}, 0], [0, {"var": "tileBase"}]],
                    },
                    "fill": {
                        "op": "if",
                        "args": [
                            {"op": "eq", "args": [{"op": "mod", "args": [{"local": "i"}, 2]}, 0]},
                            "#fbbf24",
                            "#34d399",
                        ],
                    },
                },
                "source": source,
                "target": target,
                "keyframes": keyframes,
            }
        ],
        "frames": frames,
    }


def _stage_requirements(plan: dict[str, Any]) -> list[dict[str, Any]]:
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    proof = spec.get("proof_constraints") if isinstance(spec.get("proof_constraints"), dict) else {}
    stages = proof.get("stage_requirements") if isinstance(proof.get("stage_requirements"), list) else []
    valid = [stage for stage in stages if isinstance(stage, dict)]
    if len(valid) >= 3:
        bounded = valid[:5]
        count = len(bounded)
        return [
            {
                **stage,
                "id": str(
                    stage.get("id")
                    or ("source" if index == 0 else "target" if index == count - 1 else f"transform-{index}")
                ),
                "role": "source" if index == 0 else "target" if index == count - 1 else "intermediate",
                "at": 0.0 if index == 0 else 1.0 if index == count - 1 else round(index / (count - 1), 6),
                "intent": str(stage.get("intent") or "展示几何关系"),
            }
            for index, stage in enumerate(bounded)
        ]
    return [
        {"id": "source", "role": "source", "at": 0.0, "intent": "观察源图元集合"},
        {"id": "transform", "role": "intermediate", "at": 0.5, "intent": "观察中间重排状态"},
        {"id": "target", "role": "target", "at": 1.0, "intent": "解释目标度量关系"},
    ]


def _validate_piece_template(
    piece: object,
    *,
    index: int,
    state_names: set[str],
    definitions: dict[str, Any],
    definition_names: set[str],
    require_index_independent_geometry: bool,
    budget: list[int],
    errors: list[dict[str, Any]],
) -> None:
    path = f"pieces[{index}]"
    if not isinstance(piece, dict):
        errors.append(_issue("invalid_piece_template", "图元模板必须是对象", path=path))
        return
    tag = str(piece.get("tag", "")).lower()
    if tag not in _ALLOWED_TAGS:
        errors.append(_issue("invalid_piece_tag", "图元 tag 不在白名单", path=path, tag=tag))
    repeat = piece.get("repeat")
    local_names: set[str] = set()
    if repeat is not None:
        if not isinstance(repeat, dict) or set(repeat) != {"count", "index"}:
            errors.append(_issue("invalid_piece_repeat", "repeat 仅允许 count/index", path=path))
        else:
            local = str(repeat.get("index", ""))
            if not _IDENTIFIER_RE.fullmatch(local):
                errors.append(_issue("invalid_repeat_index", "repeat.index 不合法", path=path))
            else:
                local_names.add(local)
            _validate_expression(
                repeat.get("count"),
                path=f"{path}.repeat.count",
                state_names=state_names,
                definition_names=definition_names,
                local_names=set(),
                depth=0,
                budget=budget,
                errors=errors,
            )
    _validate_expression(
        piece.get("id"),
        path=f"{path}.id",
        state_names=state_names,
        definition_names=definition_names,
        local_names=local_names,
        depth=0,
        budget=budget,
        errors=errors,
    )
    attrs = piece.get("attrs")
    allowed_attrs = _COMMON_ATTRS | _TAG_ATTRS.get(tag, set())
    if not isinstance(attrs, dict) or not attrs:
        errors.append(_issue("invalid_piece_attrs", "attrs 必须是非空对象", path=path))
    else:
        for name, expression in attrs.items():
            if name not in allowed_attrs:
                errors.append(_issue("forbidden_piece_attr", "图元属性不在白名单", path=path, attr=name))
            _validate_expression(
                expression,
                path=f"{path}.attrs.{name}",
                state_names=state_names,
                definition_names=definition_names,
                local_names=local_names,
                depth=0,
                budget=budget,
                errors=errors,
            )
            if (
                repeat is not None
                and require_index_independent_geometry
                and name in _TAG_ATTRS.get(tag, set())
                and _expression_depends_on_local(expression, local_names, definitions)
            ):
                errors.append(
                    _issue(
                        "repeat_geometry_depends_on_index",
                        "全等 repeat 图元的局部几何不得依赖 repeat 索引；朝向和位置只能写入变换",
                        path=f"{path}.attrs.{name}",
                        attr=name,
                    )
                )
    for transform_name in ("source", "target"):
        transform = piece.get(transform_name)
        if not isinstance(transform, dict) or not transform:
            errors.append(_issue("invalid_transform", f"{transform_name} 必须是对象", path=path))
            continue
        unknown = set(transform) - _TRANSFORM_KEYS
        if unknown:
            errors.append(_issue("forbidden_transform_field", "变换字段不在白名单", path=path, fields=sorted(unknown)))
        for name, expression in transform.items():
            _validate_expression(
                expression,
                path=f"{path}.{transform_name}.{name}",
                state_names=state_names,
                definition_names=definition_names,
                local_names=local_names,
                depth=0,
                budget=budget,
                errors=errors,
            )
    keyframes = piece.get("keyframes")
    if keyframes is not None:
        if not isinstance(keyframes, list) or not 2 <= len(keyframes) <= 5:
            errors.append(_issue("invalid_transform_keyframes", "keyframes 必须包含 2~5 个阶段", path=path))
        else:
            previous_at = -1.0
            for frame_index, keyframe in enumerate(keyframes):
                frame_path = f"{path}.keyframes[{frame_index}]"
                if not isinstance(keyframe, dict):
                    errors.append(_issue("invalid_transform_keyframe", "变换阶段必须是对象", path=frame_path))
                    continue
                at = _finite_float(keyframe.get("at"))
                if at is None or not 0 <= at <= 1 or at <= previous_at:
                    errors.append(
                        _issue("invalid_transform_keyframe_at", "变换阶段 at 必须在 0~1 严格递增", path=frame_path)
                    )
                else:
                    previous_at = at
                unknown = set(keyframe) - {"at", *_TRANSFORM_KEYS}
                if unknown:
                    errors.append(
                        _issue(
                            "forbidden_transform_keyframe_field",
                            "变换阶段字段不在白名单",
                            path=frame_path,
                            fields=sorted(unknown),
                        )
                    )
                for name, expression in keyframe.items():
                    if name != "at":
                        _validate_expression(
                            expression,
                            path=f"{frame_path}.{name}",
                            state_names=state_names,
                            definition_names=definition_names,
                            local_names=local_names,
                            depth=0,
                            budget=budget,
                            errors=errors,
                        )
            if isinstance(keyframes[0], dict) and keyframes[0].get("at") != 0:
                errors.append(_issue("missing_initial_transform_keyframe", "第一个变换阶段 at 必须为 0", path=path))
            if isinstance(keyframes[-1], dict) and keyframes[-1].get("at") != 1:
                errors.append(_issue("missing_final_transform_keyframe", "最后一个变换阶段 at 必须为 1", path=path))


def _expression_depends_on_local(
    expression: object,
    local_names: set[str],
    definitions: dict[str, Any],
    resolving: set[str] | None = None,
) -> bool:
    if isinstance(expression, list):
        return any(_expression_depends_on_local(item, local_names, definitions, resolving) for item in expression)
    if not isinstance(expression, dict):
        return False
    if set(expression) == {"local"}:
        return str(expression.get("local")) in local_names
    if set(expression) == {"var"}:
        name = str(expression.get("var"))
        if name not in definitions or name in (resolving or set()):
            return False
        return _expression_depends_on_local(
            definitions[name],
            local_names,
            definitions,
            {*resolving, name} if resolving else {name},
        )
    return any(
        _expression_depends_on_local(value, local_names, definitions, resolving) for value in expression.values()
    )


def _piece_congruence_required(plan: dict[str, Any]) -> bool:
    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    proof = spec.get("proof_constraints") if isinstance(spec.get("proof_constraints"), dict) else {}
    invariants = proof.get("measure_invariants")
    return isinstance(invariants, list) and "piece_congruence" in invariants


def _validate_expression(
    expression: object,
    *,
    path: str,
    state_names: set[str],
    definition_names: set[str],
    local_names: set[str],
    depth: int,
    budget: list[int],
    errors: list[dict[str, Any]],
) -> None:
    budget[0] += 1
    if depth > MAX_EXPRESSION_DEPTH:
        errors.append(_issue("expression_too_deep", "表达式嵌套过深", path=path))
        return
    if expression is None or isinstance(expression, bool):
        errors.append(_issue("invalid_expression_literal", "表达式不允许 null/布尔字面量", path=path))
        return
    if isinstance(expression, (int, float, str)):
        if isinstance(expression, float) and not math.isfinite(expression):
            errors.append(_issue("non_finite_literal", "表达式包含非有限数值", path=path))
        if isinstance(expression, str) and len(expression) > 500:
            errors.append(_issue("expression_string_too_long", "表达式字符串过长", path=path))
        return
    if isinstance(expression, list):
        if len(expression) > 64:
            errors.append(_issue("expression_array_too_long", "表达式数组过长", path=path))
        for index, item in enumerate(expression):
            _validate_expression(
                item,
                path=f"{path}[{index}]",
                state_names=state_names,
                definition_names=definition_names,
                local_names=local_names,
                depth=depth + 1,
                budget=budget,
                errors=errors,
            )
        return
    if not isinstance(expression, dict):
        errors.append(_issue("invalid_expression", "表达式必须是字面量、数组、ref 或 op", path=path))
        return
    if set(expression) == {"op", "args"}:
        _validate_operator_expression(
            expression,
            path=path,
            state_names=state_names,
            definition_names=definition_names,
            local_names=local_names,
            depth=depth,
            budget=budget,
            errors=errors,
        )
        return
    if len(expression) != 1:
        errors.append(_issue("invalid_expression", "表达式对象只能包含一个 ref 或 op/args", path=path))
        return
    kind, value = next(iter(expression.items()))
    if kind == "state":
        if value not in state_names:
            errors.append(_issue("unknown_state_reference", "引用了计划外状态变量", path=path, name=value))
        return
    if kind == "var":
        if value not in definition_names:
            errors.append(_issue("unknown_definition_reference", "引用了未知 definition", path=path, name=value))
        return
    if kind == "local":
        if value not in local_names:
            errors.append(_issue("unknown_local_reference", "引用了 repeat 范围外局部变量", path=path, name=value))
        return
    errors.append(_issue("invalid_expression_reference", "表达式引用类型不合法", path=path, reference=kind))


def _validate_operator_expression(
    expression: dict[str, Any],
    *,
    path: str,
    state_names: set[str],
    definition_names: set[str],
    local_names: set[str],
    depth: int,
    budget: list[int],
    errors: list[dict[str, Any]],
) -> None:
    op = expression.get("op")
    args = expression.get("args")
    if not isinstance(op, str) or op not in _ALLOWED_OPS or not isinstance(args, list):
        errors.append(_issue("forbidden_expression_operator", "表达式操作符或 args 不合法", path=path, operator=op))
        return
    count = len(args)
    valid_arity = (
        (op in _UNARY_OPS and count == 1)
        or (op in _BINARY_OPS and count == 2)
        or (op in _FOLD_OPS and 2 <= count <= 16)
        or (op in _TERNARY_OPS and count == 3)
        or (op in _VARIADIC_OPS and 1 <= count <= 16)
        or (op == "fixed" and count == 2)
        or (op == "points" and 1 <= count <= 40)
        or (op == "sector_path" and count in {5, 6})
    )
    if not valid_arity:
        errors.append(_issue("invalid_operator_arity", "表达式参数数量不合法", path=path, operator=op, count=count))
    for index, item in enumerate(args):
        _validate_expression(
            item,
            path=f"{path}.args[{index}]",
            state_names=state_names,
            definition_names=definition_names,
            local_names=local_names,
            depth=depth + 1,
            budget=budget,
            errors=errors,
        )


def _plan_state_names(plan: dict[str, Any]) -> set[str]:
    interactive = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    return {
        str(item.get("name"))
        for item in interactive.get("variables", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }


def _sample_states(plan: dict[str, Any]) -> list[tuple[str, dict[str, float]]]:
    interactive = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    variables = [item for item in interactive.get("variables", []) if isinstance(item, dict)]
    states: list[tuple[str, dict[str, float]]] = []
    for label, field in (("default", "default"), ("minimum", "min"), ("maximum", "max")):
        states.append(
            (
                label,
                {
                    str(item.get("name")): _finite_float(item.get(field)) or 0.0
                    for item in variables
                    if str(item.get("name") or "").strip()
                },
            )
        )
    return states


def sample_geometry_states(plan: dict[str, Any]) -> list[tuple[str, dict[str, float]]]:
    """Return bounded plan states used by deterministic geometry verification."""
    return _sample_states(plan)


def expand_geometry_ir(ir: dict[str, Any], state: dict[str, float]) -> list[dict[str, Any]]:
    """Evaluate the restricted IR into concrete pieces for local verification."""
    return _expand_geometry(ir, state)


def _expand_geometry(ir: dict[str, Any], state: dict[str, float]) -> list[dict[str, Any]]:
    definitions = ir.get("definitions", {})
    cache: dict[tuple[str, tuple[tuple[str, float], ...]], Any] = {}
    resolving: set[tuple[str, tuple[tuple[str, float], ...]]] = set()

    def resolve(name: str, locals_: dict[str, float]) -> Any:
        key = (name, tuple(sorted(locals_.items())))
        if key in cache:
            return cache[key]
        if key in resolving:
            raise ValueError(f"cyclic_definition:{name}")
        resolving.add(key)
        value = _evaluate_expression(definitions[name], state, locals_, resolve)
        resolving.remove(key)
        cache[key] = value
        return value

    output: list[dict[str, Any]] = []
    for template in ir.get("pieces", []):
        repeat = template.get("repeat")
        if repeat:
            count_value = _evaluate_expression(repeat["count"], state, {}, resolve)
            count = int(round(_number(count_value)))
            if not 1 <= count <= MAX_EXPANDED_PIECES:
                raise ValueError(f"invalid_repeat_count:{count}")
            scopes = [{str(repeat["index"]): float(index)} for index in range(count)]
        else:
            scopes = [{}]
        for locals_ in scopes:
            attrs = {
                name: _evaluate_expression(expr, state, locals_, resolve) for name, expr in template["attrs"].items()
            }
            source = {
                name: _evaluate_expression(expr, state, locals_, resolve) for name, expr in template["source"].items()
            }
            target = {
                name: _evaluate_expression(expr, state, locals_, resolve) for name, expr in template["target"].items()
            }
            keyframes = [
                {
                    "at": frame["at"],
                    **{
                        name: _evaluate_expression(expr, state, locals_, resolve)
                        for name, expr in frame.items()
                        if name != "at"
                    },
                }
                for frame in template.get("keyframes", [])
            ]
            output.append(
                {
                    "id": _evaluate_expression(template["id"], state, locals_, resolve),
                    "tag": template["tag"],
                    "attrs": attrs,
                    "source": source,
                    "target": target,
                    "keyframes": keyframes,
                }
            )
    return output


def _evaluate_expression(expression: object, state: dict[str, float], locals_: dict[str, float], resolve: Any) -> Any:
    if isinstance(expression, (int, float, str)) and not isinstance(expression, bool):
        return expression
    if isinstance(expression, list):
        return [_evaluate_expression(item, state, locals_, resolve) for item in expression]
    if not isinstance(expression, dict):
        raise ValueError("invalid_expression")
    if "state" in expression:
        return state[expression["state"]]
    if "local" in expression:
        return locals_[expression["local"]]
    if "var" in expression:
        return resolve(expression["var"], locals_)
    op = expression["op"]
    args = [_evaluate_expression(item, state, locals_, resolve) for item in expression["args"]]
    return _apply_operator(op, args)


def _apply_operator(op: str, args: list[Any]) -> Any:
    numbers = [_number(value) for value in args] if op not in {"concat", "if", "points"} else []
    if op == "add":
        return sum(numbers)
    if op == "sub":
        return numbers[0] - sum(numbers[1:])
    if op == "mul":
        return math.prod(numbers)
    if op == "div":
        result = numbers[0]
        for divisor in numbers[1:]:
            if divisor == 0:
                raise ValueError("division_by_zero")
            result /= divisor
        return result
    if op == "pow":
        return numbers[0] ** numbers[1]
    if op == "mod":
        if numbers[1] == 0:
            raise ValueError("modulo_by_zero")
        return numbers[0] % numbers[1]
    if op == "min":
        return min(numbers)
    if op == "max":
        return max(numbers)
    if op == "clamp":
        return max(numbers[1], min(numbers[2], numbers[0]))
    if op == "neg":
        return -numbers[0]
    if op == "abs":
        return abs(numbers[0])
    if op == "sqrt":
        return math.sqrt(numbers[0])
    if op == "sin":
        return math.sin(numbers[0])
    if op == "cos":
        return math.cos(numbers[0])
    if op == "tan":
        return math.tan(numbers[0])
    if op == "asin":
        return math.asin(numbers[0])
    if op == "acos":
        return math.acos(numbers[0])
    if op == "atan":
        return math.atan(numbers[0])
    if op == "atan2":
        return math.atan2(numbers[0], numbers[1])
    if op == "hypot":
        return math.hypot(numbers[0], numbers[1])
    if op == "round":
        return round(numbers[0])
    if op == "floor":
        return math.floor(numbers[0])
    if op == "ceil":
        return math.ceil(numbers[0])
    if op == "rad_to_deg":
        return numbers[0] * 180 / math.pi
    if op == "deg_to_rad":
        return numbers[0] * math.pi / 180
    if op == "eq":
        return args[0] == args[1]
    if op == "ne":
        return args[0] != args[1]
    if op == "lt":
        return numbers[0] < numbers[1]
    if op == "lte":
        return numbers[0] <= numbers[1]
    if op == "gt":
        return numbers[0] > numbers[1]
    if op == "gte":
        return numbers[0] >= numbers[1]
    if op == "if":
        return args[1] if bool(args[0]) else args[2]
    if op == "concat":
        return "".join(_string(value) for value in args)
    if op == "fixed":
        return f"{numbers[0]:.{max(0, min(6, int(numbers[1])))}f}"
    if op == "points":
        return " ".join(
            f"{_number(pair[0]):g},{_number(pair[1]):g}" for pair in args if isinstance(pair, list) and len(pair) == 2
        )
    if op == "sector_path":
        cx, cy, radius, start, end = numbers[:5]
        if radius <= 0:
            raise ValueError("non_positive_sector_radius")
        large = 1 if abs(end - start) > math.pi else 0
        sweep = 1 if len(numbers) == 5 or numbers[5] != 0 else 0
        return f"M {cx:g} {cy:g} L {cx + radius * math.cos(start):g} {cy + radius * math.sin(start):g} A {radius:g} {radius:g} 0 {large} {sweep} {cx + radius * math.cos(end):g} {cy + radius * math.sin(end):g} Z"
    raise ValueError(f"unknown_operator:{op}")


def _validate_expanded_geometry(pieces: list[dict[str, Any]]) -> None:
    if not 1 <= len(pieces) <= MAX_EXPANDED_PIECES:
        raise ValueError(f"invalid_piece_count:{len(pieces)}")
    ids: set[str] = set()
    changed = False
    for piece in pieces:
        piece_id = str(piece["id"])
        if not piece_id or len(piece_id) > 80 or piece_id in ids:
            raise ValueError(f"invalid_piece_id:{piece_id}")
        ids.add(piece_id)
        tag = str(piece["tag"])
        attrs = piece["attrs"]
        missing = _REQUIRED_ATTRS.get(tag, set()) - set(attrs)
        if missing:
            raise ValueError(f"missing_attrs:{piece_id}:{','.join(sorted(missing))}")
        for name, value in attrs.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not math.isfinite(float(value)):
                    raise ValueError(f"non_finite_attr:{piece_id}:{name}")
                if name in _POSITIVE_ATTRS and float(value) <= 0:
                    raise ValueError(f"non_positive_attr:{piece_id}:{name}")
            elif not isinstance(value, str) or not value or len(value) > 1_000:
                raise ValueError(f"invalid_attr:{piece_id}:{name}")
        for transform_name in ("source", "target"):
            transform = piece[transform_name]
            for key in _TRANSFORM_KEYS:
                fallback = 1.0 if key in {"scale", "opacity"} else 0.0
                value = _number(transform.get(key, fallback))
                if not math.isfinite(value):
                    raise ValueError(f"non_finite_transform:{piece_id}:{transform_name}:{key}")
                if key == "scale" and value <= 0:
                    raise ValueError(f"non_positive_scale:{piece_id}:{transform_name}")
                if key == "opacity" and not 0 <= value <= 1:
                    raise ValueError(f"invalid_opacity:{piece_id}:{transform_name}")
        for index, keyframe in enumerate(piece.get("keyframes", [])):
            for key in _TRANSFORM_KEYS:
                fallback = 1.0 if key in {"scale", "opacity"} else 0.0
                value = _number(keyframe.get(key, fallback))
                if not math.isfinite(value):
                    raise ValueError(f"non_finite_keyframe:{piece_id}:{index}:{key}")
                if key == "scale" and value <= 0:
                    raise ValueError(f"non_positive_keyframe_scale:{piece_id}:{index}")
                if key == "opacity" and not 0 <= value <= 1:
                    raise ValueError(f"invalid_keyframe_opacity:{piece_id}:{index}")
        for key in _TRANSFORM_KEYS:
            fallback = 1.0 if key in {"scale", "opacity"} else 0.0
            if _number(piece["source"].get(key, fallback)) != _number(piece["target"].get(key, fallback)):
                changed = True
    if not changed:
        raise ValueError("source_target_transforms_identical")


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number(value: object) -> float:
    number = _finite_float(value)
    if number is None:
        raise ValueError(f"expected_finite_number:{value}")
    return number


def _string(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _issue(issue_type: str, message: str, **details: object) -> dict[str, Any]:
    return {"type": issue_type, "message": message, "line": None, **details}


def _report(errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "结构化几何 IR 契约检查完成",
        "errors": errors,
        "warnings": warnings,
    }


_COMPILED_RUNTIME = r"""const sceneIRRuntime=Object.freeze({
 num(value){const number=Number(value);if(!Number.isFinite(number))throw new Error('ir_non_finite_number');return number;},
 str(value){return typeof value==='number'&&Number.isInteger(value)?String(value):String(value);},
 op(name,args){const n=(index)=>this.num(args[index]);if(name==='add')return args.reduce((sum,value)=>sum+this.num(value),0);if(name==='sub')return args.slice(1).reduce((result,value)=>result-this.num(value),n(0));if(name==='mul')return args.reduce((product,value)=>product*this.num(value),1);if(name==='div')return args.slice(1).reduce((result,value)=>{const divisor=this.num(value);if(divisor===0)throw new Error('ir_division_by_zero');return result/divisor;},n(0));if(name==='pow')return Math.pow(n(0),n(1));if(name==='mod'){if(n(1)===0)throw new Error('ir_modulo_by_zero');return n(0)%n(1);}if(name==='min')return Math.min(...args.map(this.num));if(name==='max')return Math.max(...args.map(this.num));if(name==='clamp')return Math.max(n(1),Math.min(n(2),n(0)));if(name==='neg')return -n(0);if(name==='abs')return Math.abs(n(0));if(name==='sqrt')return Math.sqrt(n(0));if(name==='sin')return Math.sin(n(0));if(name==='cos')return Math.cos(n(0));if(name==='tan')return Math.tan(n(0));if(name==='asin')return Math.asin(n(0));if(name==='acos')return Math.acos(n(0));if(name==='atan')return Math.atan(n(0));if(name==='atan2')return Math.atan2(n(0),n(1));if(name==='hypot')return Math.hypot(n(0),n(1));if(name==='round')return Math.round(n(0));if(name==='floor')return Math.floor(n(0));if(name==='ceil')return Math.ceil(n(0));if(name==='rad_to_deg')return n(0)*180/Math.PI;if(name==='deg_to_rad')return n(0)*Math.PI/180;if(name==='eq')return args[0]===args[1];if(name==='ne')return args[0]!==args[1];if(name==='lt')return n(0)<n(1);if(name==='lte')return n(0)<=n(1);if(name==='gt')return n(0)>n(1);if(name==='gte')return n(0)>=n(1);if(name==='if')return args[0]?args[1]:args[2];if(name==='concat')return args.map(this.str).join('');if(name==='fixed')return n(0).toFixed(Math.max(0,Math.min(6,Math.round(n(1)))));if(name==='points')return args.filter((pair)=>Array.isArray(pair)&&pair.length===2).map((pair)=>this.num(pair[0])+','+this.num(pair[1])).join(' ');if(name==='sector_path'){const cx=n(0),cy=n(1),r=n(2),a=n(3),b=n(4),large=Math.abs(b-a)>Math.PI?1:0,sweep=args.length===5||n(5)!==0?1:0;return 'M '+cx+' '+cy+' L '+(cx+r*Math.cos(a))+' '+(cy+r*Math.sin(a))+' A '+r+' '+r+' 0 '+large+' '+sweep+' '+(cx+r*Math.cos(b))+' '+(cy+r*Math.sin(b))+' Z';}throw new Error('ir_unknown_operator:'+name);},
 evaluate(node,context){if(typeof node==='number'||typeof node==='string')return node;if(Array.isArray(node))return node.map((item)=>this.evaluate(item,context));if(!node||typeof node!=='object')throw new Error('ir_invalid_expression');if(Object.prototype.hasOwnProperty.call(node,'state'))return context.state[node.state];if(Object.prototype.hasOwnProperty.call(node,'local'))return context.locals[node.local];if(Object.prototype.hasOwnProperty.call(node,'var'))return context.resolve(node.var);if(Object.prototype.hasOwnProperty.call(node,'op'))return this.op(node.op,node.args.map((item)=>this.evaluate(item,context)));throw new Error('ir_invalid_expression');},
 build(ir,state){const cache=new Map(),resolving=new Set(),context={state,locals:{},resolve:(name)=>{const key=name+'|'+JSON.stringify(context.locals);if(cache.has(key))return cache.get(key);if(resolving.has(key))throw new Error('ir_cyclic_definition:'+name);resolving.add(key);const value=this.evaluate(ir.definitions[name],context);resolving.delete(key);cache.set(key,value);return value;}};const pieces=[];for(const template of ir.pieces){context.locals={};let scopes=[{}];if(template.repeat){const count=Math.round(this.num(this.evaluate(template.repeat.count,context)));if(count<1||count>80)throw new Error('ir_invalid_repeat_count:'+count);scopes=Array.from({length:count},(_,index)=>({[template.repeat.index]:index}));}for(const locals of scopes){context.locals=locals;const attrs=Object.fromEntries(Object.entries(template.attrs).map(([key,value])=>[key,this.evaluate(value,context)]));const transform=(value)=>Object.fromEntries(Object.entries(value).map(([key,item])=>[key,this.num(this.evaluate(item,context))]));const transformKeyframes=(template.keyframes||[]).map((frame)=>({at:this.num(frame.at),...transform(Object.fromEntries(Object.entries(frame).filter(([key])=>key!=='at')))}));pieces.push({id:this.str(this.evaluate(template.id,context)),tag:template.tag,attrs,sourceTransform:transform(template.source),targetTransform:transform(template.target),transformKeyframes});}}return {pieces};}
});
const sceneModule={structureKey(state){return __TOPOLOGY__.map((key)=>String(state[key])).join('|')||'fixed';},buildGeometry(state){return sceneIRRuntime.build(sceneIR,state);},deriveFrame(geometry,state,progress){return sceneMath.interpolatePieces(geometry.pieces,progress);},deriveDisplay(state,progress){let selected=sceneIR.frames[0]||{at:0,caption:'观察图形重排。',formula:'',step:0};for(const frame of sceneIR.frames)if(Number(progress)>=Number(frame.at||0))selected=frame;return {caption:String(selected.caption||''),formula:String(selected.formula||''),step:Number(selected.step||0)};}};"""
