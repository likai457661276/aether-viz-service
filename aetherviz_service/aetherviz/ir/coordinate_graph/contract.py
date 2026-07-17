"""Contract adapter for one coordinate plane using the shared math expression core."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from typing import Any

from aetherviz_service.aetherviz.ir.linked_coordinate.contract import (
    LINKED_COORDINATE_IR_VERSION,
    linked_coordinate_ir_response_schema,
    normalize_linked_coordinate_ir,
    parse_linked_coordinate_ir,
    parse_linked_coordinate_ir_candidates,
    validate_linked_coordinate_ir,
)

COORDINATE_GRAPH_IR_VERSION = "aetherviz.coordinate-graph-ir.v1"
COORDINATE_GRAPH_IR_MAX_CHARS = 12_000


class CoordinateGraphIRValidationError(ValueError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(report.get("summary") or "coordinate_graph_ir_invalid")


def coordinate_graph_ir_response_schema() -> dict[str, Any]:
    schema = deepcopy(linked_coordinate_ir_response_schema())
    schema["properties"]["version"]["enum"] = [COORDINATE_GRAPH_IR_VERSION]
    schema["properties"]["coordinate_systems"]["maxItems"] = 1
    schema["properties"]["curves"]["maxItems"] = 6
    schema["properties"]["points"]["maxItems"] = 12
    schema["properties"]["links"]["maxItems"] = 8
    return schema


def coordinate_graph_ir_candidates_response_schema() -> dict[str, Any]:
    candidate = coordinate_graph_ir_response_schema()
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


def normalize_coordinate_graph_ir(ir: object, plan: dict[str, Any]) -> object:
    if not isinstance(ir, dict):
        return ir
    candidate = deepcopy(ir)
    candidate["version"] = LINKED_COORDINATE_IR_VERSION
    normalized = normalize_linked_coordinate_ir(candidate, plan)
    if isinstance(normalized, dict):
        normalized["version"] = COORDINATE_GRAPH_IR_VERSION
    return normalized


def validate_coordinate_graph_ir(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    original_version = ir.get("version") if isinstance(ir, dict) else None
    normalized = normalize_coordinate_graph_ir(ir, plan)
    if not isinstance(normalized, dict):
        return _report(
            [{"type": "invalid_coordinate_graph_ir", "message": "坐标图 IR 必须是 JSON 对象"}],
            [],
        )
    base = deepcopy(normalized)
    base["version"] = LINKED_COORDINATE_IR_VERSION
    report = validate_linked_coordinate_ir(base, plan)
    errors = list(report.get("errors", []))
    warnings = list(report.get("warnings", []))
    systems = normalized.get("coordinate_systems")
    if not isinstance(systems, list) or len(systems) != 1:
        errors.append(
            {
                "type": "coordinate_graph_requires_single_system",
                "message": "单视图坐标图 IR 必须且只能包含一个 coordinate_system",
            }
        )
    if original_version != COORDINATE_GRAPH_IR_VERSION:
        errors.append(
            {
                "type": "unsupported_coordinate_graph_ir_version",
                "message": "单视图坐标图 IR 版本不受支持",
            }
        )
    serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > COORDINATE_GRAPH_IR_MAX_CHARS:
        errors.append({"type": "coordinate_graph_ir_too_long", "message": "单视图坐标图 IR 超过长度上限"})
    variables = {
        str(item.get("name"))
        for item in ((plan.get("interactive_spec") or {}).get("variables", []))
        if isinstance(item, dict) and item.get("name") and not item.get("computed")
    }
    if len(variables) > 1:
        animation = normalized.get("animation") if isinstance(normalized.get("animation"), dict) else {}
        keyframes = animation.get("keyframes")
        frame_states = [
            set(item.get("state", {}))
            for item in keyframes
            if isinstance(item, dict) and isinstance(item.get("state"), dict)
        ] if isinstance(keyframes, list) else []
        covered = set.intersection(*frame_states) if frame_states else set()
        if not isinstance(keyframes, list) or len(keyframes) < 2 or not variables <= covered:
            errors.append(
                {
                    "type": "missing_multi_state_keyframes",
                    "message": "多变量坐标图必须用关键帧覆盖全部可调变量",
                }
            )
    return _report(errors, warnings)


def rank_coordinate_graph_ir_candidates(candidates: list[object], plan: dict[str, Any]) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        normalized = normalize_coordinate_graph_ir(candidate, plan)
        report = validate_coordinate_graph_ir(normalized, plan)
        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        reports.append(
            {
                "index": index,
                "eligible": report["ok"],
                "error_count": len(report["errors"]),
                "warning_count": len(report["warnings"]),
                "chars": len(serialized),
                "fingerprint": sha256(serialized.encode("utf-8")).hexdigest(),
                "report": report,
                "ir": normalized,
            }
        )
    ordered = sorted(
        reports,
        key=lambda item: (
            not item["eligible"],
            item["error_count"],
            item["warning_count"],
            item["chars"],
            item["fingerprint"],
        ),
    )
    selected = next((item for item in ordered if item["eligible"]), None)
    repair = ordered[0] if ordered else None
    return {
        "ok": selected is not None,
        "selected_index": selected["index"] if selected else None,
        "selected_ir": selected["ir"] if selected else None,
        "repair_index": repair["index"] if repair else None,
        "repair_candidate": repair["ir"] if repair else None,
        "repair_report": repair["report"] if repair else None,
        "candidates": [
            {key: item[key] for key in ("index", "eligible", "error_count", "warning_count", "chars", "fingerprint", "report")}
            for item in reports
        ],
    }


def compile_coordinate_graph_ir(ir: dict[str, Any], plan: dict[str, Any]) -> str:
    normalized = normalize_coordinate_graph_ir(ir, plan)
    report = validate_coordinate_graph_ir(normalized, plan)
    if not report["ok"] or not isinstance(normalized, dict):
        raise CoordinateGraphIRValidationError(report)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _report(errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": not errors,
        "severity": "error" if errors else ("warning" if warnings else "ok"),
        "summary": f"发现 {len(errors)} 个错误，{len(warnings)} 个提示" if errors or warnings else "坐标图 IR 检查通过",
        "errors": errors,
        "warnings": warnings,
    }


parse_coordinate_graph_ir = parse_linked_coordinate_ir
parse_coordinate_graph_ir_candidates = parse_linked_coordinate_ir_candidates
