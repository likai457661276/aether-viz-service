"""Strict finite graph, set, ordering and sequence contract."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from hashlib import sha256
from typing import Any

DISCRETE_STRUCTURE_IR_VERSION = "aetherviz.discrete-structure-ir.v1"
DISCRETE_STRUCTURE_IR_MAX_CHARS = 24_000
VIEW_TYPES = frozenset({"graph", "tree", "set", "sequence", "permutation"})


class DiscreteStructureIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "discrete_structure_ir_invalid")


def discrete_structure_ir_response_schema() -> dict[str, Any]:
    visibility = {
        "visible_from": {"type": "number", "minimum": 0, "maximum": 1},
        "visible_to": {"type": "number", "minimum": 0, "maximum": 1},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "animation", "nodes", "edges", "sets", "sequences", "views", "observation"],
        "properties": {
            "version": {"type": "string", "enum": [DISCRETE_STRUCTURE_IR_VERSION]},
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
            "nodes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label", "order"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "label": {"type": "string", "minLength": 1, "maxLength": 32},
                        "order": {"type": "integer", "minimum": 0, "maximum": 63},
                        "group": {"type": "string", "maxLength": 48},
                        **visibility,
                    },
                },
            },
            "edges": {
                "type": "array",
                "maxItems": 128,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "source", "target", "directed", "label"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "directed": {"type": "boolean"},
                        "label": {"type": "string", "maxLength": 32},
                        **visibility,
                    },
                },
            },
            "sets": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label", "members"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "label": {"type": "string", "minLength": 1, "maxLength": 32},
                        "members": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": {"type": "string"}},
                    },
                },
            },
            "sequences": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "label", "terms", "recurrence"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "label": {"type": "string", "minLength": 1, "maxLength": 32},
                        "terms": {"type": "array", "minItems": 2, "maxItems": 48, "items": {"type": "number"}},
                        "recurrence": {"type": "string", "minLength": 1, "maxLength": 100},
                    },
                },
            },
            "views": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "type", "title"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 48},
                        "type": {"type": "string", "enum": sorted(VIEW_TYPES)},
                        "title": {"type": "string", "minLength": 1, "maxLength": 48},
                        "ref": {"type": "string"},
                        "root": {"type": "string"},
                    },
                },
            },
            "observation": {"type": "string", "minLength": 1, "maxLength": 240},
        },
    }


def discrete_structure_ir_candidates_response_schema() -> dict[str, Any]:
    item = discrete_structure_ir_response_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {"candidates": {"type": "array", "minItems": 2, "maxItems": 2, "items": item}},
    }


def normalize_discrete_structure_ir(ir: object, plan: dict[str, Any]) -> object:
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
    candidate.setdefault("edges", [])
    candidate.setdefault("sets", [])
    candidate.setdefault("sequences", [])
    return candidate


def validate_discrete_structure_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    value = normalize_discrete_structure_ir(ir, plan)
    errors: list[dict[str, str]] = []
    if not isinstance(value, dict):
        return _report([_error("invalid_discrete_ir", "离散结构 IR 必须是对象")])
    if value.get("version") != DISCRETE_STRUCTURE_IR_VERSION:
        errors.append(_error("unsupported_discrete_ir_version", "离散结构 IR 版本不受支持"))
    animation = value.get("animation") if isinstance(value.get("animation"), dict) else {}
    variables = {item["name"] for item in _plan_variables(plan)}
    if animation.get("variable") not in variables:
        errors.append(_error("unknown_discrete_animation_state", "动画变量必须引用计划变量"))
    try:
        if not 2 <= float(animation.get("duration")) <= 12:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(_error("invalid_discrete_duration", "动画时长必须为 2~12 秒"))
    nodes = value.get("nodes") if isinstance(value.get("nodes"), list) else []
    edges = value.get("edges") if isinstance(value.get("edges"), list) else []
    sets = value.get("sets") if isinstance(value.get("sets"), list) else []
    sequences = value.get("sequences") if isinstance(value.get("sequences"), list) else []
    views = value.get("views") if isinstance(value.get("views"), list) else []
    if not 1 <= len(nodes) <= 64 or len(edges) > 128 or len(sets) > 8 or len(sequences) > 6 or not 1 <= len(views) <= 5:
        errors.append(_error("invalid_discrete_scene_size", "离散对象或视图数量超出范围"))
    node_ids = _ids(nodes, "node", errors)
    _ids(edges, "edge", errors)
    set_ids = _ids(sets, "set", errors)
    sequence_ids = _ids(sequences, "sequence", errors)
    _ids(views, "view", errors)
    orders = [item.get("order") for item in nodes if isinstance(item, dict)]
    if len(orders) != len(set(orders)) or not all(
        isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in orders
    ):
        errors.append(_error("invalid_node_order", "节点 order 必须为非负且唯一的整数"))
    for item in nodes + edges:
        _validate_visibility(item, errors)
    adjacency: dict[str, list[str]] = {item: [] for item in node_ids}
    indegree = {item: 0 for item in node_ids}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("source"), edge.get("target")
        if source not in node_ids or target not in node_ids or source == target:
            errors.append(_error("invalid_discrete_edge", f"边 {edge.get('id')} 的端点无效"))
            continue
        adjacency[str(source)].append(str(target))
        indegree[str(target)] += 1
    for item in sets:
        refs = item.get("members") if isinstance(item, dict) else None
        if not isinstance(refs, list) or len(refs) != len(set(refs)) or not set(refs) <= node_ids:
            errors.append(
                _error("invalid_set_members", f"集合 {item.get('id') if isinstance(item, dict) else ''} 包含未知成员")
            )
    for item in sequences:
        terms = item.get("terms") if isinstance(item, dict) else None
        if (
            not isinstance(terms, list)
            or not 2 <= len(terms) <= 48
            or not all(
                isinstance(term, (int, float)) and not isinstance(term, bool) and math.isfinite(float(term))
                for term in terms
            )
        ):
            errors.append(_error("invalid_sequence_terms", "序列项必须是 2~48 个有限数"))
    for view in views:
        if not isinstance(view, dict) or view.get("type") not in VIEW_TYPES:
            errors.append(_error("invalid_discrete_view", "离散视图类型不受支持"))
            continue
        kind, ref = view["type"], view.get("ref")
        if kind == "set" and ref not in set_ids:
            errors.append(_error("invalid_set_view_ref", "集合视图必须引用集合"))
        if kind == "sequence" and ref not in sequence_ids:
            errors.append(_error("invalid_sequence_view_ref", "序列视图必须引用序列"))
        if kind == "tree":
            root = view.get("root")
            if root not in node_ids:
                errors.append(_error("invalid_tree_root", "树视图必须引用根节点"))
            elif (
                any(not edge.get("directed") for edge in edges if isinstance(edge, dict))
                or _has_cycle(adjacency)
                or any(value > 1 for value in indegree.values())
                or any(indegree[item] != (0 if item == root else 1) for item in node_ids)
            ):
                errors.append(_error("invalid_tree_topology", "树视图要求有向、无环、单根且每个非根节点入度为 1"))
    return _report(errors)


def parse_discrete_structure_ir(raw: str) -> dict[str, Any]:
    if len(raw) > DISCRETE_STRUCTURE_IR_MAX_CHARS:
        raise ValueError("discrete_structure_ir_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("discrete_structure_ir_not_object")
    return value


def parse_discrete_structure_ir_candidates(raw: str) -> list[dict[str, Any]]:
    value = json.loads(raw)
    candidates = value.get("candidates") if isinstance(value, dict) else None
    if (
        not isinstance(candidates, list)
        or len(candidates) != 2
        or not all(isinstance(item, dict) for item in candidates)
    ):
        raise ValueError("discrete_structure_ir_candidates_invalid")
    return candidates


def rank_discrete_structure_ir_candidates(candidates: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    ranked = []
    for candidate in candidates:
        normalized = normalize_discrete_structure_ir(candidate, plan)
        report = validate_discrete_structure_ir(normalized, plan)
        if report["ok"]:
            ranked.append(
                (len(normalized.get("views", [])) * 10 + len(normalized.get("nodes", [])), normalized, report)
            )
    if ranked:
        ranked.sort(key=lambda item: item[0], reverse=True)
        return {"ok": True, "selected_ir": ranked[0][1], "report": ranked[0][2]}
    candidate = normalize_discrete_structure_ir(candidates[0], plan) if candidates else {}
    return {
        "ok": False,
        "repair_candidate": candidate,
        "repair_report": validate_discrete_structure_ir(candidate, plan),
    }


def compile_discrete_structure_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    normalized = normalize_discrete_structure_ir(ir, plan)
    report = validate_discrete_structure_ir(normalized, plan)
    if not report["ok"]:
        raise DiscreteStructureIRValidationError(report)
    payload = deepcopy(normalized)
    payload["contract_hash"] = sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _has_cycle(adjacency: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in adjacency[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in adjacency)


def _validate_visibility(item: object, errors: list[dict[str, str]]) -> None:
    if not isinstance(item, dict):
        return
    low, high = item.get("visible_from", 0), item.get("visible_to", 1)
    if (
        not isinstance(low, (int, float))
        or isinstance(low, bool)
        or not isinstance(high, (int, float))
        or isinstance(high, bool)
        or not 0 <= float(low) <= float(high) <= 1
    ):
        errors.append(_error("invalid_discrete_visibility", f"对象 {item.get('id')} 的可见区间无效"))


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
        "summary": f"发现 {len(errors)} 个错误" if errors else "离散结构 IR 检查通过",
        "errors": errors,
        "warnings": [],
    }
