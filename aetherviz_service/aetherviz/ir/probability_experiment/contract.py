"""Strict contract for finite seeded probability experiments."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from hashlib import sha256
from typing import Any

PROBABILITY_EXPERIMENT_IR_VERSION = "aetherviz.probability-experiment-ir.v1"
PROBABILITY_EXPERIMENT_IR_MAX_CHARS = 20_000
VIEW_TYPES = frozenset({"sample_space", "frequency_chart", "probability_tree"})


class ProbabilityExperimentIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "probability_experiment_ir_invalid")


def probability_experiment_ir_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "animation", "seed", "outcomes", "events", "views", "observation"],
        "properties": {
            "version": {"type": "string", "enum": [PROBABILITY_EXPERIMENT_IR_VERSION]},
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
            "seed": {"type": "integer", "minimum": 1, "maximum": 2147483646},
            "outcomes": {
                "type": "array",
                "minItems": 2,
                "maxItems": 48,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label", "weight", "path"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "label": {"type": "string", "minLength": 1, "maxLength": 32},
                        "weight": {"type": "number", "exclusiveMinimum": 0},
                        "path": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {"type": "string", "minLength": 1, "maxLength": 24},
                        },
                    },
                },
            },
            "events": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label", "outcomes"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "label": {"type": "string", "minLength": 1, "maxLength": 40},
                        "outcomes": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 48,
                            "uniqueItems": True,
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "views": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "type", "title"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "type": {"type": "string", "enum": sorted(VIEW_TYPES)},
                        "title": {"type": "string", "minLength": 1, "maxLength": 48},
                        "event": {"type": "string"},
                    },
                },
            },
            "observation": {"type": "string", "minLength": 1, "maxLength": 240},
        },
    }


def probability_experiment_ir_candidates_response_schema() -> dict[str, Any]:
    item = probability_experiment_ir_response_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {"candidates": {"type": "array", "minItems": 2, "maxItems": 2, "items": item}},
    }


def normalize_probability_experiment_ir(ir: object, plan: dict[str, Any]) -> object:
    if not isinstance(ir, dict):
        return ir
    candidate = deepcopy(ir)
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


def validate_probability_experiment_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    value = normalize_probability_experiment_ir(ir, plan)
    errors: list[dict[str, str]] = []
    if not isinstance(value, dict):
        return _report([_error("invalid_probability_ir", "概率试验 IR 必须是对象")])
    if value.get("version") != PROBABILITY_EXPERIMENT_IR_VERSION:
        errors.append(_error("unsupported_probability_ir_version", "概率试验 IR 版本不受支持"))
    animation = value.get("animation") if isinstance(value.get("animation"), dict) else {}
    variables = {item["name"] for item in _plan_variables(plan)}
    if animation.get("variable") not in variables:
        errors.append(_error("unknown_probability_animation_state", "动画变量必须引用计划变量"))
    try:
        if not 2 <= float(animation.get("duration")) <= 12:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(_error("invalid_probability_duration", "动画时长必须为 2~12 秒"))
    outcomes = value.get("outcomes") if isinstance(value.get("outcomes"), list) else []
    events = value.get("events") if isinstance(value.get("events"), list) else []
    views = value.get("views") if isinstance(value.get("views"), list) else []
    if not 2 <= len(outcomes) <= 48 or not 1 <= len(events) <= 12 or not 1 <= len(views) <= 3:
        errors.append(_error("invalid_probability_scene_size", "结果、事件或视图数量超出范围"))
    outcome_ids = _ids(outcomes, "outcome", errors)
    event_ids = _ids(events, "event", errors)
    _ids(views, "view", errors)
    total = 0.0
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        weight = outcome.get("weight")
        if (
            not isinstance(weight, (int, float))
            or isinstance(weight, bool)
            or not math.isfinite(float(weight))
            or float(weight) <= 0
        ):
            errors.append(_error("invalid_outcome_weight", "样本点权重必须为有限正数"))
        else:
            total += float(weight)
        path = outcome.get("path")
        if (
            not isinstance(path, list)
            or not 1 <= len(path) <= 4
            or not all(isinstance(item, str) and item for item in path)
        ):
            errors.append(_error("invalid_outcome_path", "每个样本点须有 1~4 层概率树路径"))
    if total <= 0:
        errors.append(_error("empty_probability_mass", "总概率权重必须为正"))
    for event in events:
        refs = event.get("outcomes") if isinstance(event, dict) else None
        if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)) or not set(refs) <= outcome_ids:
            errors.append(
                _error(
                    "invalid_event_outcomes",
                    f"事件 {event.get('id') if isinstance(event, dict) else ''} 引用了无效样本点",
                )
            )
    for view in views:
        if not isinstance(view, dict) or view.get("type") not in VIEW_TYPES:
            errors.append(_error("invalid_probability_view", "概率视图类型不受支持"))
            continue
        if view.get("type") == "frequency_chart" and view.get("event") not in event_ids:
            errors.append(_error("invalid_frequency_event", "频率图必须引用已声明事件"))
    seed = value.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or not 1 <= seed <= 2147483646:
        errors.append(_error("invalid_probability_seed", "随机种子超出范围"))
    return _report(errors)


def event_probabilities(ir: dict[str, Any]) -> dict[str, float]:
    weights = {str(item["id"]): float(item["weight"]) for item in ir.get("outcomes", [])}
    total = sum(weights.values())
    return {
        str(event["id"]): sum(weights[item] for item in event["outcomes"]) / total for event in ir.get("events", [])
    }


def parse_probability_experiment_ir(raw: str) -> dict[str, Any]:
    if len(raw) > PROBABILITY_EXPERIMENT_IR_MAX_CHARS:
        raise ValueError("probability_experiment_ir_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("probability_experiment_ir_not_object")
    return value


def parse_probability_experiment_ir_candidates(raw: str) -> list[dict[str, Any]]:
    value = json.loads(raw)
    candidates = value.get("candidates") if isinstance(value, dict) else None
    if (
        not isinstance(candidates, list)
        or len(candidates) != 2
        or not all(isinstance(item, dict) for item in candidates)
    ):
        raise ValueError("probability_experiment_ir_candidates_invalid")
    return candidates


def rank_probability_experiment_ir_candidates(candidates: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    ranked = []
    for candidate in candidates:
        normalized = normalize_probability_experiment_ir(candidate, plan)
        report = validate_probability_experiment_ir(normalized, plan)
        if report["ok"]:
            ranked.append(
                (len(normalized.get("views", [])) * 10 + len(normalized.get("events", [])), normalized, report)
            )
    if ranked:
        ranked.sort(key=lambda item: item[0], reverse=True)
        return {"ok": True, "selected_ir": ranked[0][1], "report": ranked[0][2]}
    candidate = normalize_probability_experiment_ir(candidates[0], plan) if candidates else {}
    return {
        "ok": False,
        "repair_candidate": candidate,
        "repair_report": validate_probability_experiment_ir(candidate, plan),
    }


def compile_probability_experiment_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    normalized = normalize_probability_experiment_ir(ir, plan)
    report = validate_probability_experiment_ir(normalized, plan)
    if not report["ok"]:
        raise ProbabilityExperimentIRValidationError(report)
    payload = deepcopy(normalized)
    payload["event_probabilities"] = event_probabilities(normalized)
    payload["contract_hash"] = sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _plan_variables(plan: dict[str, Any]) -> list[dict[str, float]]:
    spec = plan.get("interactive_spec") if isinstance(plan.get("interactive_spec"), dict) else {}
    result = []
    for item in spec.get("variables", []):
        if not isinstance(item, dict) or item.get("computed") or not item.get("name"):
            continue
        try:
            low, high, default = float(item.get("min")), float(item.get("max")), float(item.get("default"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(low) and math.isfinite(high) and low < high and low <= default <= high:
            result.append({"name": str(item["name"]), "min": low, "max": high, "default": default})
    return result


def _ids(items: list[object], kind: str, errors: list[dict[str, str]]) -> set[str]:
    ids = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
    if len(ids) != len(items) or any(not item for item in ids) or len(ids) != len(set(ids)):
        errors.append(_error(f"invalid_{kind}_ids", f"{kind} id 必须非空且唯一"))
    return set(ids)


def _error(kind: str, message: str) -> dict[str, str]:
    return {"type": kind, "message": message}


def _report(errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else "ok",
        "summary": f"发现 {len(errors)} 个错误" if errors else "概率试验 IR 检查通过",
        "errors": errors,
        "warnings": [],
    }
