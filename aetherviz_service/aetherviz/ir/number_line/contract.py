"""Deterministic contract for interactive one-dimensional number-line scenes."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from hashlib import sha256
from typing import Any

NUMBER_LINE_IR_VERSION = "aetherviz.number-line-ir.v1"
NUMBER_LINE_IR_MAX_CHARS = 12_000
EXPRESSION_OPERATORS = {"add", "sub", "mul", "div", "min", "max", "neg", "abs"}
ENDPOINT_STYLES = {"open", "closed"}
RAY_DIRECTIONS = {"left", "right"}
INVARIANT_TYPES = {
    "ordered_interval",
    "point_on_number_line",
    "distance_equals_absolute_difference",
    "movement_equals_sum",
    "set_operation_consistent",
}


class NumberLineIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "number_line_ir_invalid")


def number_line_ir_response_schema() -> dict[str, Any]:
    expression = {
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
                "properties": {
                    "op": {"type": "string", "enum": sorted(EXPRESSION_OPERATORS)},
                    "args": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/expression"},
                        "minItems": 1,
                        "maxItems": 8,
                    },
                },
                "required": ["op", "args"],
            },
        ]
    }
    visual_common = {
        "id": {"type": "string", "minLength": 1, "maxLength": 48},
        "track": {"type": "string", "minLength": 1, "maxLength": 48},
        "label": {"type": "string", "maxLength": 80},
        "color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": {"expression": expression},
        "required": [
            "version",
            "domain",
            "animation",
            "tracks",
            "points",
            "intervals",
            "rays",
            "distances",
            "movements",
            "invariants",
        ],
        "properties": {
            "version": {"type": "string", "enum": [NUMBER_LINE_IR_VERSION]},
            "domain": {
                "type": "array",
                "prefixItems": [{"type": "number"}, {"type": "number"}],
                "minItems": 2,
                "maxItems": 2,
            },
            "animation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["variable", "from", "to", "duration", "keyframes"],
                "properties": {
                    "variable": {"type": "string"},
                    "from": {"$ref": "#/$defs/expression"},
                    "to": {"$ref": "#/$defs/expression"},
                    "duration": {"type": "number", "minimum": 2, "maximum": 12},
                    "keyframes": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["progress", "state"],
                            "properties": {
                                "progress": {"type": "number", "minimum": 0, "maximum": 1},
                                "state": {"type": "object", "additionalProperties": {"type": "number"}},
                            },
                        },
                    },
                },
            },
            "tracks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "label": {"type": "string", "minLength": 1, "maxLength": 80},
                    },
                },
            },
            "points": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [*visual_common, "value", "endpoint"],
                    "properties": {
                        **visual_common,
                        "value": {"$ref": "#/$defs/expression"},
                        "endpoint": {"type": "string", "enum": sorted(ENDPOINT_STYLES)},
                    },
                },
            },
            "intervals": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [*visual_common, "start", "end", "left_endpoint", "right_endpoint"],
                    "properties": {
                        **visual_common,
                        "start": {"$ref": "#/$defs/expression"},
                        "end": {"$ref": "#/$defs/expression"},
                        "left_endpoint": {"type": "string", "enum": sorted(ENDPOINT_STYLES)},
                        "right_endpoint": {"type": "string", "enum": sorted(ENDPOINT_STYLES)},
                    },
                },
            },
            "rays": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [*visual_common, "boundary", "direction", "endpoint"],
                    "properties": {
                        **visual_common,
                        "boundary": {"$ref": "#/$defs/expression"},
                        "direction": {"type": "string", "enum": sorted(RAY_DIRECTIONS)},
                        "endpoint": {"type": "string", "enum": sorted(ENDPOINT_STYLES)},
                    },
                },
            },
            "distances": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [*visual_common, "start", "end"],
                    "properties": {
                        **visual_common,
                        "start": {"$ref": "#/$defs/expression"},
                        "end": {"$ref": "#/$defs/expression"},
                    },
                },
            },
            "movements": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [*visual_common, "start", "delta"],
                    "properties": {
                        **visual_common,
                        "start": {"$ref": "#/$defs/expression"},
                        "delta": {"$ref": "#/$defs/expression"},
                    },
                },
            },
            "invariants": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "type", "refs"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "type": {"type": "string", "enum": sorted(INVARIANT_TYPES)},
                        "refs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 6,
                        },
                    },
                },
            },
        },
    }


def number_line_ir_candidates_response_schema() -> dict[str, Any]:
    candidate = number_line_ir_response_schema()
    definitions = candidate.pop("$defs")
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": definitions,
        "required": ["candidates"],
        "properties": {
            "candidates": {"type": "array", "minItems": 2, "maxItems": 2, "items": candidate}
        },
    }


def normalize_number_line_ir(ir: object, plan: dict[str, Any]) -> object:
    if not isinstance(ir, dict):
        return ir
    normalized = deepcopy(ir)
    ranges = _state_ranges(plan)
    animation = normalized.get("animation") if isinstance(normalized.get("animation"), dict) else {}
    variable = str(animation.get("variable") or "")
    if ranges and variable not in ranges:
        variable = next(iter(ranges))
        animation["variable"] = variable
    if variable in ranges:
        minimum, default, maximum = ranges[variable]
        animation["from"] = minimum
        animation["to"] = maximum
        animation.setdefault("duration", 6)
        if len(ranges) == 1:
            animation.setdefault("keyframes", [])
        elif not isinstance(animation.get("keyframes"), list):
            animation["keyframes"] = [
                {"progress": 0, "state": {name: values[0] for name, values in ranges.items()}},
                {"progress": 1, "state": {name: values[2] for name, values in ranges.items()}},
            ]
        _ = default
    normalized["animation"] = animation
    return normalized


def validate_number_line_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_number_line_ir(ir, plan)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(normalized, dict):
        return _report([_issue("invalid_number_line_ir", "数轴 IR 必须是 JSON 对象")], [])
    serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > NUMBER_LINE_IR_MAX_CHARS:
        errors.append(_issue("number_line_ir_too_long", "数轴 IR 超过长度上限"))
    if normalized.get("version") != NUMBER_LINE_IR_VERSION:
        errors.append(_issue("unsupported_number_line_ir_version", "数轴 IR 版本不受支持"))

    domain = normalized.get("domain")
    if not isinstance(domain, list) or len(domain) != 2 or any(_number(value) is None for value in domain):
        errors.append(_issue("invalid_number_line_domain", "数轴 domain 必须包含两个有限数值"))
        domain_bounds = (-10.0, 10.0)
    else:
        domain_bounds = (float(domain[0]), float(domain[1]))
        if domain_bounds[0] >= domain_bounds[1] or domain_bounds[1] - domain_bounds[0] > 10_000:
            errors.append(_issue("invalid_number_line_domain", "数轴 domain 必须严格递增且跨度受限"))

    ranges = _state_ranges(plan)
    if not ranges:
        errors.append(_issue("number_line_requires_state", "数轴 IR 当前版本至少需要一个计划状态变量"))
    animation = normalized.get("animation") if isinstance(normalized.get("animation"), dict) else {}
    variable = str(animation.get("variable") or "")
    if variable not in ranges:
        errors.append(_issue("invalid_number_line_animation_variable", "动画变量必须引用计划状态"))
    duration = _number(animation.get("duration"))
    if duration is None or not 2 <= duration <= 12:
        errors.append(_issue("invalid_number_line_animation_duration", "动画时长必须在 2~12 秒"))
    for key in ("from", "to"):
        _validate_expr(animation.get(key), ranges, errors, f"animation.{key}")
    _validate_keyframes(animation.get("keyframes"), ranges, errors)

    tracks = _objects(normalized.get("tracks"), 1, 4, "tracks", errors)
    track_ids = _unique_ids(tracks, "track", errors)
    collections = {
        "points": _objects(normalized.get("points"), 0, 16, "points", errors),
        "intervals": _objects(normalized.get("intervals"), 0, 16, "intervals", errors),
        "rays": _objects(normalized.get("rays"), 0, 8, "rays", errors),
        "distances": _objects(normalized.get("distances"), 0, 8, "distances", errors),
        "movements": _objects(normalized.get("movements"), 0, 8, "movements", errors),
    }
    object_ids: set[str] = set()
    expression_fields = {
        "points": ("value",),
        "intervals": ("start", "end"),
        "rays": ("boundary",),
        "distances": ("start", "end"),
        "movements": ("start", "delta"),
    }
    for collection_name, items in collections.items():
        identifiers = _unique_ids(items, collection_name[:-1], errors)
        duplicate_cross_type = object_ids & identifiers
        if duplicate_cross_type:
            errors.append(_issue("duplicate_number_line_object", "数轴对象 id 必须全局唯一"))
        object_ids.update(identifiers)
        for item in items:
            if item.get("track") not in track_ids:
                errors.append(_issue("unknown_number_line_track", "数轴对象引用了不存在的轨道", id=item.get("id")))
            if item.get("color") and not _valid_color(item.get("color")):
                errors.append(_issue("invalid_number_line_color", "数轴对象颜色必须是六位十六进制", id=item.get("id")))
            for field in expression_fields[collection_name]:
                _validate_expr(item.get(field), ranges, errors, f"{collection_name}.{item.get('id')}.{field}")
    if not object_ids:
        errors.append(_issue("empty_number_line_scene", "数轴 IR 至少需要一个可视对象"))

    invariants = _objects(normalized.get("invariants"), 1, 12, "invariants", errors)
    _unique_ids(invariants, "invariant", errors)
    for invariant in invariants:
        kind = invariant.get("type")
        refs = invariant.get("refs") if isinstance(invariant.get("refs"), list) else []
        if kind not in INVARIANT_TYPES:
            errors.append(_issue("invalid_number_line_invariant", "数轴不变量类型不受支持"))
        if not refs or any(ref not in object_ids for ref in refs):
            errors.append(_issue("invalid_number_line_invariant_ref", "数轴不变量必须引用已声明对象"))

    if not errors:
        for state_name, state in _sample_states(ranges):
            try:
                for item in collections["intervals"]:
                    start = _eval(item["start"], state)
                    end = _eval(item["end"], state)
                    if start > end:
                        raise ValueError(f"interval_not_ordered:{item['id']}")
                for collection_name, items in collections.items():
                    for item in items:
                        for field in expression_fields[collection_name]:
                            value = _eval(item[field], state)
                            if not math.isfinite(value) or not domain_bounds[0] <= value <= domain_bounds[1]:
                                raise ValueError(f"object_outside_domain:{item['id']}")
                        if collection_name == "movements":
                            end = _eval(item["start"], state) + _eval(item["delta"], state)
                            if not domain_bounds[0] <= end <= domain_bounds[1]:
                                raise ValueError(f"movement_outside_domain:{item['id']}")
            except (ValueError, ArithmeticError) as exc:
                errors.append(_issue("number_line_ir_semantics", f"{state_name} 状态不满足数轴语义：{exc}"))
                break
    return _report(errors, warnings)


def rank_number_line_ir_candidates(candidates: list[object], plan: dict[str, Any]) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        normalized = normalize_number_line_ir(candidate, plan)
        report = validate_number_line_ir(normalized, plan)
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


def parse_number_line_ir(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text.startswith("{"):
        raise ValueError("missing_number_line_ir_object")
    value, end = json.JSONDecoder().raw_decode(text)
    if text[end:].strip() or not isinstance(value, dict):
        raise ValueError("invalid_number_line_ir_object")
    return value


def parse_number_line_ir_candidates(raw: str) -> list[object]:
    payload = parse_number_line_ir(raw)
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("number_line_candidates_must_contain_2_items")
    return candidates


def compile_number_line_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    normalized = normalize_number_line_ir(ir, plan)
    report = validate_number_line_ir(normalized, plan)
    if not report["ok"] or not isinstance(normalized, dict):
        raise NumberLineIRValidationError(report)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _validate_keyframes(value: object, ranges: dict[str, tuple[float, float, float]], errors: list[dict]) -> None:
    if len(ranges) == 1 and value == []:
        return
    if not isinstance(value, list) or not 2 <= len(value) <= 8:
        errors.append(_issue("invalid_number_line_keyframes", "多变量数轴动画需要 2~8 个关键帧"))
        return
    previous = -1.0
    for index, frame in enumerate(value):
        if not isinstance(frame, dict) or _number(frame.get("progress")) is None:
            errors.append(_issue("invalid_number_line_keyframe", "关键帧结构无效", index=index))
            continue
        progress = float(frame["progress"])
        state = frame.get("state") if isinstance(frame.get("state"), dict) else {}
        if progress <= previous or not 0 <= progress <= 1 or set(state) != set(ranges):
            errors.append(_issue("invalid_number_line_keyframe", "关键帧必须递增并覆盖全部计划变量", index=index))
        previous = progress
        for name, raw in state.items():
            number = _number(raw)
            if name not in ranges or number is None or not ranges[name][0] <= number <= ranges[name][2]:
                errors.append(_issue("number_line_keyframe_out_of_range", "关键帧状态超出计划范围", index=index))
    if value and (value[0].get("progress") != 0 or value[-1].get("progress") != 1):
        errors.append(_issue("number_line_keyframes_must_span_timeline", "关键帧必须覆盖 0~1"))


def _validate_expr(value: object, ranges: dict[str, tuple[float, float, float]], errors: list[dict], path: str) -> None:
    if _number(value) is not None:
        return
    if not isinstance(value, dict):
        errors.append(_issue("invalid_number_line_expression", f"{path} 表达式无效"))
        return
    if set(value) == {"state"} and str(value["state"]) in ranges:
        return
    if set(value) == {"op", "args"} and value.get("op") in EXPRESSION_OPERATORS and isinstance(value.get("args"), list):
        args = value["args"]
        arity = len(args)
        if (value["op"] in {"neg", "abs"} and arity != 1) or (
            value["op"] not in {"neg", "abs"} and arity < 2
        ):
            errors.append(_issue("invalid_number_line_expression_arity", f"{path} 操作数数量无效"))
            return
        for index, item in enumerate(args):
            _validate_expr(item, ranges, errors, f"{path}.args[{index}]")
        return
    errors.append(_issue("invalid_number_line_expression_reference", f"{path} 含未知状态或操作符"))


def _eval(value: object, state: dict[str, float]) -> float:
    number = _number(value)
    if number is not None:
        return number
    if not isinstance(value, dict):
        raise ValueError("invalid_expression")
    if set(value) == {"state"}:
        return float(state[str(value["state"])])
    args = [_eval(item, state) for item in value.get("args", [])]
    op = value.get("op")
    if op == "add":
        return sum(args)
    if op == "sub":
        return args[0] - sum(args[1:])
    if op == "mul":
        return math.prod(args)
    if op == "div":
        return args[0] / math.prod(args[1:])
    if op == "min":
        return min(args)
    if op == "max":
        return max(args)
    if op == "neg":
        return -args[0]
    if op == "abs":
        return abs(args[0])
    raise ValueError("invalid_expression")


def _state_ranges(plan: dict[str, Any]) -> dict[str, tuple[float, float, float]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    result: dict[str, tuple[float, float, float]] = {}
    for item in spec.get("variables", []):
        if not isinstance(item, dict) or item.get("computed") or not item.get("name"):
            continue
        minimum, default, maximum = (_number(item.get(key)) for key in ("min", "default", "max"))
        if minimum is not None and default is not None and maximum is not None and minimum <= default <= maximum:
            result[str(item["name"])] = (minimum, default, maximum)
    return result


def _sample_states(ranges: dict[str, tuple[float, float, float]]) -> list[tuple[str, dict[str, float]]]:
    defaults = {name: values[1] for name, values in ranges.items()}
    result = [("default", defaults)]
    for name, (minimum, _default, maximum) in ranges.items():
        result.append((f"{name}:minimum", {**defaults, name: minimum}))
        result.append((f"{name}:maximum", {**defaults, name: maximum}))
    return result


def _objects(value: object, minimum: int, maximum: int, label: str, errors: list[dict]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        errors.append(_issue("invalid_number_line_collection", f"{label} 数量必须在 {minimum}~{maximum}"))
        return []
    return [item for item in value if isinstance(item, dict)]


def _unique_ids(items: list[dict[str, Any]], label: str, errors: list[dict]) -> set[str]:
    identifiers: set[str] = set()
    for item in items:
        identifier = str(item.get("id") or "")
        if not identifier or identifier in identifiers:
            errors.append(_issue("invalid_number_line_id", f"{label} id 缺失或重复"))
        identifiers.add(identifier)
    return identifiers


def _valid_color(value: object) -> bool:
    text = str(value or "")
    return len(text) == 7 and text.startswith("#") and all(char in "0123456789abcdefABCDEF" for char in text[1:])


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _issue(kind: str, message: str, **details: Any) -> dict[str, Any]:
    return {"type": kind, "message": message, **details}


def _report(errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else ("warning" if warnings else "ok"),
        "summary": f"发现 {len(errors)} 个错误，{len(warnings)} 个提示" if errors or warnings else "数轴 IR 检查通过",
        "errors": errors,
        "warnings": warnings,
    }
