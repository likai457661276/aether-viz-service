"""Deterministic validation, scoring and ranking for geometry IR candidates."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from aetherviz_service.aetherviz.tools.recomposition_assembly import evaluate_target_assembly
from aetherviz_service.aetherviz.tools.recomposition_ir import (
    expand_geometry_ir,
    normalize_geometry_ir,
    sample_geometry_states,
    validate_geometry_ir,
)
from aetherviz_service.aetherviz.tools.recomposition_math import evaluate_mathematical_invariants
from aetherviz_service.aetherviz.tools.recomposition_semantics import evaluate_recomposition_semantics

CANVAS_WIDTH = 960.0
CANVAS_HEIGHT = 560.0
SCORE_WEIGHTS = {
    "schema": 15.0,
    "mathematical_invariants": 15.0,
    "target_assembly": 20.0,
    "teaching_stages": 15.0,
    "transform_text_consistency": 10.0,
    "piece_count": 8.0,
    "motion_range": 8.0,
    "bounds_and_scale": 4.0,
    "fallback_avoidance": 5.0,
}


def rank_geometry_ir_candidates(
    candidates: list[object],
    plan: dict[str, Any],
    *,
    origins: list[str] | None = None,
) -> dict[str, Any]:
    """Reject deterministic failures and rank survivors with stable tie-breaking."""
    evaluated = [
        _evaluate_candidate(candidate, plan, index, (origins or [])[index] if origins and index < len(origins) else "model")
        for index, candidate in enumerate(candidates)
    ]
    eligible = [item for item in evaluated if item["eligible"]]
    eligible.sort(key=lambda item: (-item["score"], item["fingerprint"], item["index"]))
    closest = sorted(
        evaluated,
        key=lambda item: (
            len(item["hard_failures"]),
            -item["score"],
            item["fingerprint"],
            item["index"],
        ),
    )
    selected = eligible[0] if eligible else None
    return {
        "ok": selected is not None,
        "selected_index": selected["index"] if selected else None,
        "selected_ir": selected.get("ir") if selected else None,
        "selected_score": selected["score"] if selected else None,
        "repair_candidate": closest[0].get("ir") if closest else None,
        "repair_candidate_index": closest[0]["index"] if closest else None,
        "candidates": [_public_report(item) for item in evaluated],
        "ranking": [item["index"] for item in eligible],
        "weights": SCORE_WEIGHTS,
        "decision": (
            f"candidate-{selected['index']} selected at {selected['score']:.3f}"
            if selected
            else "all candidates rejected by deterministic hard checks"
        ),
    }


def public_geometry_ir_ranking(report: dict[str, Any]) -> dict[str, Any]:
    """Remove candidate payloads while preserving the reproducible decision evidence."""
    return {
        key: value
        for key, value in report.items()
        if key not in {"selected_ir", "repair_candidate"}
    }


def _evaluate_candidate(candidate: object, plan: dict[str, Any], index: int, origin: str) -> dict[str, Any]:
    normalization_error = ""
    try:
        ir = normalize_geometry_ir(candidate, plan) if isinstance(candidate, dict) else candidate
    except (TypeError, ValueError) as exc:
        ir = candidate
        normalization_error = str(exc)
    fingerprint = _fingerprint(ir)
    contract = validate_geometry_ir(ir, plan)
    if normalization_error:
        contract = {
            "ok": False,
            "errors": [{"type": "geometry_ir_normalization", "message": normalization_error}],
            "warnings": [],
        }
    if not isinstance(ir, dict) or not contract["ok"]:
        failures = _error_types(contract, "schema")
        return _candidate_result(
            index=index,
            origin=origin,
            ir=ir if isinstance(ir, dict) else None,
            fingerprint=fingerprint,
            hard_failures=failures,
            components={name: 0.0 for name in SCORE_WEIGHTS},
            details={"schema": contract},
        )

    math_report = evaluate_mathematical_invariants(ir, plan)
    assembly_report = evaluate_target_assembly(ir, plan)
    semantic_report = evaluate_recomposition_semantics(ir, plan)
    safety_report = _evaluate_motion_safety(ir, plan)
    stage_errors = [
        error
        for error in semantic_report.get("errors", [])
        if not str(error.get("type", "")).startswith(("mathematical_", "target_assembly_"))
    ]
    hard_failures = [
        *_error_types(math_report, "mathematics"),
        *_error_types(assembly_report, "assembly"),
        *[f"teaching:{error.get('type', 'unknown')}" for error in stage_errors],
        *[f"safety:{error.get('type', 'unknown')}" for error in safety_report["errors"]],
    ]
    piece_score, piece_details = _score_piece_count(ir, plan)
    text_score, text_details = _score_transform_text_consistency(ir, plan)
    components = {
        "schema": SCORE_WEIGHTS["schema"],
        "mathematical_invariants": SCORE_WEIGHTS["mathematical_invariants"] * _mathematics_score(math_report),
        "target_assembly": SCORE_WEIGHTS["target_assembly"] * _assembly_score(assembly_report),
        "teaching_stages": SCORE_WEIGHTS["teaching_stages"] if not stage_errors else 0.0,
        "transform_text_consistency": SCORE_WEIGHTS["transform_text_consistency"] * text_score,
        "piece_count": SCORE_WEIGHTS["piece_count"] * piece_score,
        "motion_range": SCORE_WEIGHTS["motion_range"] * safety_report["motion_score"],
        "bounds_and_scale": SCORE_WEIGHTS["bounds_and_scale"] * safety_report["bounds_score"],
        "fallback_avoidance": SCORE_WEIGHTS["fallback_avoidance"] * _origin_score(origin),
    }
    return _candidate_result(
        index=index,
        origin=origin,
        ir=ir,
        fingerprint=fingerprint,
        hard_failures=hard_failures,
        components=components,
        details={
            "schema": contract,
            "mathematics": math_report,
            "target_assembly": assembly_report,
            "teaching_semantics": semantic_report,
            "transform_text": text_details,
            "piece_count": piece_details,
            "motion_safety": safety_report,
        },
    )


def _mathematics_score(report: dict[str, Any]) -> float:
    if not report.get("ok"):
        return 0.0
    return max(0.0, min(1.0, _finite(report.get("relation_coverage"), 1.0)))


def _assembly_score(report: dict[str, Any]) -> float:
    if not report.get("ok"):
        return 0.0
    states = report.get("states", [])
    if not states:
        return 1.0
    scores = [
        _finite(item.get("rectangularity"), 0)
        * (1 - min(1.0, _finite(item.get("overlap_ratio"), 1)))
        / max(1, int(item.get("component_count", 1)))
        for item in states
    ]
    return sum(scores) / len(scores)


def _evaluate_motion_safety(ir: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    samples = 0
    safe_bounds = 0
    reasonable_motion = 0
    for state_label, state in sample_geometry_states(plan):
        pieces = expand_geometry_ir(ir, state)
        for piece in pieces:
            transforms = [piece["source"], *piece.get("keyframes", []), piece["target"]]
            for transform in transforms:
                samples += 1
                x = _finite(transform.get("x"), math.inf)
                y = _finite(transform.get("y"), math.inf)
                scale = _finite(transform.get("scale"), math.inf)
                if not (-CANVAS_WIDTH <= x <= CANVAS_WIDTH * 2 and -CANVAS_HEIGHT <= y <= CANVAS_HEIGHT * 2):
                    errors.append({"type": "gross_transform_out_of_bounds", "state": state_label, "piece_id": piece["id"]})
                if not 0.05 <= scale <= 8:
                    errors.append({"type": "unsafe_transform_scale", "state": state_label, "piece_id": piece["id"], "scale": scale})
                if 24 <= x <= CANVAS_WIDTH - 24 and 24 <= y <= CANVAS_HEIGHT - 24 and 0.2 <= scale <= 3.5:
                    safe_bounds += 1
            source = piece["source"]
            target = piece["target"]
            distance = math.hypot(_finite(target.get("x"), 0) - _finite(source.get("x"), 0), _finite(target.get("y"), 0) - _finite(source.get("y"), 0))
            if 24 <= distance <= math.hypot(CANVAS_WIDTH, CANVAS_HEIGHT) * 0.85:
                reasonable_motion += 1
    unique_errors = list({json.dumps(item, sort_keys=True, ensure_ascii=False): item for item in errors}.values())
    piece_samples = sum(len(expand_geometry_ir(ir, state)) for _, state in sample_geometry_states(plan))
    return {
        "ok": not unique_errors,
        "errors": unique_errors,
        "sample_count": samples,
        "bounds_score": safe_bounds / samples if samples else 0.0,
        "motion_score": reasonable_motion / piece_samples if piece_samples else 0.0,
    }


def _score_piece_count(ir: dict[str, Any], plan: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    counts = [len(expand_geometry_ir(ir, state)) for _, state in sample_geometry_states(plan)]
    scores = [1.0 if 3 <= count <= 24 else 0.7 if 2 <= count <= 40 else 0.35 for count in counts]
    return sum(scores) / len(scores), {"counts": counts, "preferred_range": [3, 24]}


def _score_transform_text_consistency(ir: dict[str, Any], plan: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    pieces = expand_geometry_ir(ir, dict(sample_geometry_states(plan)[1][1]))
    frames = ir.get("frames", [])
    checks: list[dict[str, Any]] = []
    keyword_groups = {
        "rotation": ("旋转", "转动", "翻转"),
        "scale": ("缩放", "放大", "缩小"),
        "opacity": ("淡入", "淡出", "透明", "隐藏", "显现"),
        "motion": ("移动", "平移", "分离", "对齐", "重排", "拼合", "合并", "展开", "切分"),
    }
    for frame_index in range(1, len(frames)):
        at = _finite(frames[frame_index].get("at"), 0)
        previous_at = _finite(frames[frame_index - 1].get("at"), 0)
        text = f"{frames[frame_index].get('caption', '')} {frames[frame_index].get('formula', '')}"
        deltas = {"rotation": False, "scale": False, "opacity": False, "motion": False}
        for piece in pieces:
            left = _transform_at(piece, previous_at)
            right = _transform_at(piece, at)
            deltas["rotation"] |= abs(right["rotation"] - left["rotation"]) > 1e-6
            deltas["scale"] |= abs(right["scale"] - left["scale"]) > 1e-6
            deltas["opacity"] |= abs(right["opacity"] - left["opacity"]) > 1e-6
            deltas["motion"] |= math.hypot(right["x"] - left["x"], right["y"] - left["y"]) > 1e-6 or deltas["rotation"]
        claims = {name: any(word in text for word in words) for name, words in keyword_groups.items()}
        contradictions = sorted(name for name, claimed in claims.items() if claimed and not deltas[name])
        described = any(claims[name] and deltas[name] for name in claims)
        checks.append({"stage_id": frames[frame_index].get("stage_id"), "claims": claims, "motion": deltas, "contradictions": contradictions, "described": described})
    if not checks:
        return 0.0, {"checks": []}
    contradiction_ratio = sum(bool(item["contradictions"]) for item in checks) / len(checks)
    described_ratio = sum(bool(item["described"]) for item in checks) / len(checks)
    return max(0.0, 1.0 - contradiction_ratio) * (0.7 + 0.3 * described_ratio), {"checks": checks}


def _transform_at(piece: dict[str, Any], at: float) -> dict[str, float]:
    candidates = [*piece.get("keyframes", []), {"at": 0, **piece["source"]}, {"at": 1, **piece["target"]}]
    frame = min(candidates, key=lambda item: abs(_finite(item.get("at"), 0) - at))
    return {name: _finite(frame.get(name), 1 if name in {"scale", "opacity"} else 0) for name in ("x", "y", "rotation", "scale", "opacity")}


def _origin_score(origin: str) -> float:
    return {"model": 1.0, "repair": 0.6, "fallback": 0.0}.get(origin, 0.5)


def _candidate_result(*, index: int, origin: str, ir: dict[str, Any] | None, fingerprint: str, hard_failures: list[str], components: dict[str, float], details: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "origin": origin,
        "ir": ir,
        "fingerprint": fingerprint,
        "eligible": not hard_failures,
        "hard_failures": sorted(set(hard_failures)),
        "components": {name: round(value, 6) for name, value in components.items()},
        "score": round(sum(components.values()), 6),
        "details": details,
    }


def _public_report(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "ir"}


def _error_types(report: dict[str, Any], prefix: str) -> list[str]:
    return [f"{prefix}:{item.get('type', 'unknown')}" for item in report.get("errors", [])]


def _fingerprint(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def _finite(value: object, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback
