"""Local semantic checks for generic geometric recomposition teaching IR."""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.tools.recomposition_assembly import evaluate_target_assembly
from aetherviz_service.aetherviz.tools.recomposition_ir import (
    expand_geometry_ir,
    sample_geometry_states,
    validate_geometry_ir,
)
from aetherviz_service.aetherviz.tools.recomposition_math import evaluate_mathematical_invariants

INTERMEDIATE_EVIDENCE_THRESHOLDS = {
    "translation_px": 12.0,
    "rotation_deg": 8.0,
    "scale": 0.04,
    "opacity": 0.06,
}


def evaluate_recomposition_semantics(ir: object, plan: dict[str, Any]) -> dict[str, Any]:
    """Check geometry/text consistency without inferring any knowledge-point geometry."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    contract = validate_geometry_ir(ir, plan)
    if not contract["ok"] or not isinstance(ir, dict):
        return _report(contract.get("errors", []), warnings)

    frames = ir.get("frames", [])
    captions = [str(frame.get("caption") or "").strip() for frame in frames]
    formulas = [str(frame.get("formula") or "").strip() for frame in frames]
    if frames[0].get("at") != 0 or frames[-1].get("at") != 1:
        errors.append(_issue("teaching_endpoint_frames", "教学帧必须覆盖源状态和目标状态"))
    if any(not caption for caption in captions):
        errors.append(_issue("empty_teaching_caption", "每个教学阶段必须包含可读说明"))
    if len(set(captions)) != len(captions):
        warnings.append(_issue("duplicate_teaching_caption", "教学阶段说明存在重复"))
    if not formulas[-1]:
        errors.append(_issue("missing_conclusion_formula", "目标阶段必须给出公式或度量关系"))

    spec = plan.get("recomposition_spec") if isinstance(plan.get("recomposition_spec"), dict) else {}
    proof = spec.get("proof_constraints") if isinstance(spec.get("proof_constraints"), dict) else {}
    requirements = proof.get("stage_requirements") if isinstance(proof.get("stage_requirements"), list) else []
    stage_checks = _evaluate_teaching_stage_evidence(ir, plan, requirements)
    errors.extend(stage_checks["errors"])
    warnings.extend(stage_checks["warnings"])
    math_report = evaluate_mathematical_invariants(ir, plan)
    errors.extend(math_report["errors"])
    warnings.extend(math_report["warnings"])
    assembly_report = evaluate_target_assembly(ir, plan)
    errors.extend(assembly_report["errors"])
    warnings.extend(assembly_report["warnings"])

    return _report(
        errors,
        warnings,
        checks=[*stage_checks["checks"], *math_report["checks"], *assembly_report["checks"]],
    )


def _evaluate_teaching_stage_evidence(
    ir: dict[str, Any], plan: dict[str, Any], requirements: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    frames = ir.get("frames") if isinstance(ir.get("frames"), list) else []
    frame_by_stage = {
        str(frame.get("stage_id")): frame
        for frame in frames
        if isinstance(frame, dict) and str(frame.get("stage_id") or "")
    }
    if len(frame_by_stage) != len(frames):
        errors.append(_issue("duplicate_teaching_stage_id", "教学帧 stage_id 必须唯一"))

    required_ids = {str(stage.get("id")) for stage in requirements if str(stage.get("id") or "")}
    unexpected = sorted(set(frame_by_stage) - required_ids)
    if unexpected:
        errors.append(_issue("unexpected_teaching_stage", "教学帧包含计划外阶段", stage_ids=unexpected))

    for stage in requirements:
        stage_id = str(stage.get("id") or "")
        role = str(stage.get("role") or "")
        expected_at = _number(stage.get("at"), -1)
        frame = frame_by_stage.get(stage_id)
        if frame is None:
            errors.append(_issue("missing_teaching_stage", "缺少计划要求的教学阶段", stage_id=stage_id))
            continue
        actual_at = _number(frame.get("at"), -2)
        if abs(actual_at - expected_at) > 1e-6:
            errors.append(
                _issue(
                    "teaching_stage_timeline_mismatch",
                    "教学帧时间点与计划阶段不一致",
                    stage_id=stage_id,
                    expected=expected_at,
                    actual=actual_at,
                )
            )
        checks.append({"kind": "teaching_stage", "name": stage_id, "role": role, "at": actual_at})

    intermediate = [
        stage
        for stage in requirements
        if isinstance(stage, dict)
        and (
            stage.get("geometry_requirement") == "transform_keyframe"
            or stage.get("role") == "intermediate"
        )
    ]
    for state_label, state in sample_geometry_states(plan):
        pieces = expand_geometry_ir(ir, state)
        total = len(pieces)
        for stage in intermediate:
            stage_id = str(stage.get("id") or "")
            at = _number(stage.get("at"), -1)
            required_ratio = min(1.0, max(0.1, _number(stage.get("min_piece_ratio"), 0.5)))
            piece_evidence = [evaluate_intermediate_transform_evidence(piece, at) for piece in pieces]
            evidenced = sum(1 for evidence in piece_evidence if evidence["evidenced"])
            ratio = evidenced / total if total else 0.0
            reason_counts: dict[str, int] = {}
            for evidence in piece_evidence:
                reason = str(evidence["reason"])
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            check = {
                "kind": "intermediate_geometry",
                "name": stage_id,
                "state": state_label,
                "at": at,
                "evidenced_pieces": evidenced,
                "total_pieces": total,
                "ratio": ratio,
                "required_ratio": required_ratio,
                "reason_counts": reason_counts,
                "piece_evidence": piece_evidence,
            }
            checks.append(check)
            if ratio + 1e-9 < required_ratio:
                errors.append(
                    _issue(
                        "missing_intermediate_geometry_stage",
                        "中间教学阶段缺少足够的独立几何关键状态",
                        **check,
                    )
                )
    return {"errors": errors, "warnings": warnings, "checks": checks}


def evaluate_intermediate_transform_evidence(
    piece: dict[str, Any], at: float
) -> dict[str, Any]:
    """Return explainable, scale-aware evidence for an independent transform waypoint."""
    keyframe = next(
        (
            frame
            for frame in piece.get("keyframes", [])
            if isinstance(frame, dict) and abs(_number(frame.get("at"), -2) - at) <= 1e-6
        ),
        None,
    )
    if keyframe is None:
        return {
            "piece_id": str(piece.get("id") or ""),
            "at": at,
            "evidenced": False,
            "reason": "missing_keyframe",
            "endpoint_score": 0.0,
            "independence_score": 0.0,
            "thresholds": dict(INTERMEDIATE_EVIDENCE_THRESHOLDS),
            "metrics": {},
        }
    source = piece.get("source") if isinstance(piece.get("source"), dict) else {}
    target = piece.get("target") if isinstance(piece.get("target"), dict) else {}
    actual = _transform_vector(keyframe)
    source_vector = _transform_vector(source)
    target_vector = _transform_vector(target)
    direct = {
        key: source_vector[key] + (target_vector[key] - source_vector[key]) * at
        for key in source_vector
    }
    source_metrics = _transform_delta(actual, source_vector)
    target_metrics = _transform_delta(actual, target_vector)
    direct_metrics = _transform_delta(actual, direct)
    source_score = _evidence_score(source_metrics)
    target_score = _evidence_score(target_metrics)
    endpoint_score = min(source_score, target_score)
    independence_score = _evidence_score(direct_metrics)
    if source_score < 1.0:
        reason = "insufficient_source_separation"
    elif target_score < 1.0:
        reason = "insufficient_target_separation"
    elif independence_score < 1.0:
        reason = "insufficient_direct_path_deviation"
    else:
        reason = "independent_transform_evidence"
    return {
        "piece_id": str(piece.get("id") or ""),
        "at": at,
        "evidenced": reason == "independent_transform_evidence",
        "reason": reason,
        "endpoint_score": round(endpoint_score, 6),
        "source_separation_score": round(source_score, 6),
        "target_separation_score": round(target_score, 6),
        "independence_score": round(independence_score, 6),
        "thresholds": dict(INTERMEDIATE_EVIDENCE_THRESHOLDS),
        "metrics": {
            "from_source": _round_metrics(source_metrics),
            "from_target": _round_metrics(target_metrics),
            "from_direct_interpolation": _round_metrics(direct_metrics),
        },
    }


def _transform_vector(transform: dict[str, Any]) -> dict[str, float]:
    return {
        key: _number(transform.get(key), _transform_default(key))
        for key in ("x", "y", "rotation", "scale", "opacity")
    }


def _transform_delta(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    return {
        "translation_px": ((left["x"] - right["x"]) ** 2 + (left["y"] - right["y"]) ** 2)
        ** 0.5,
        "rotation_deg": abs(left["rotation"] - right["rotation"]),
        "scale": abs(left["scale"] - right["scale"]),
        "opacity": abs(left["opacity"] - right["opacity"]),
    }


def _evidence_score(metrics: dict[str, float]) -> float:
    return max(
        metrics[name] / threshold
        for name, threshold in INTERMEDIATE_EVIDENCE_THRESHOLDS.items()
    )


def _round_metrics(metrics: dict[str, float]) -> dict[str, float]:
    return {name: round(value, 6) for name, value in metrics.items()}


def _transform_default(key: str) -> float:
    return 1.0 if key in {"scale", "opacity"} else 0.0


def _number(value: object, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number == number and number not in {float("inf"), float("-inf")} else fallback


def _issue(issue_type: str, message: str, **details: object) -> dict[str, Any]:
    return {"type": issue_type, "message": message, **details}


def _report(
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    *,
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks or [],
    }
