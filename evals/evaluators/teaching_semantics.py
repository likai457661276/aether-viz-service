"""Local teaching-quality evaluators and adversarial fixture mutations."""

from __future__ import annotations

import copy
from typing import Any

from aetherviz_service.aetherviz.ir.recomposition.math import evaluate_mathematical_invariants
from aetherviz_service.aetherviz.ir.recomposition.ranking import rank_geometry_ir_candidates
from aetherviz_service.aetherviz.ir.recomposition.semantics import evaluate_recomposition_semantics


def evaluate_invalid_case(
    base_ir: dict[str, Any], plan: dict[str, Any], case: dict[str, Any]
) -> dict[str, Any]:
    """Apply one generic failure mutation and verify deterministic detection."""
    ir = copy.deepcopy(base_ir)
    mutated_plan = copy.deepcopy(plan)
    mutation = str(case.get("mutation") or "")
    if mutation == "remove_intermediate_stage":
        intermediate = next(
            (index for index, frame in enumerate(ir.get("frames", [])) if 0 < frame.get("at", 0) < 1),
            None,
        )
        if intermediate is not None:
            ir["frames"].pop(intermediate)
    elif mutation == "break_measure_relation":
        ir["pieces"][0]["target"]["scale"] = 1.5
    elif mutation == "claim_absent_scale_change":
        frame = next((frame for frame in ir.get("frames", []) if 0 < frame.get("at", 0) < 1), None)
        if frame:
            frame["caption"] = "缩放图元并观察尺度变化"
    elif mutation == "move_target_out_of_bounds":
        ir["pieces"][0]["target"]["x"] = 5000
        if ir["pieces"][0].get("keyframes"):
            ir["pieces"][0]["keyframes"][-1]["x"] = 5000
    elif mutation == "require_false_target_assembly":
        proof = mutated_plan["recomposition_spec"]["proof_constraints"]
        proof["target_assembly"] = [
            {
                "id": "target-rectangle",
                "type": "approximate_rectangle",
                "max_components": 1,
                "max_overlap_ratio": 0.05,
                "min_rectangularity": 0.85,
                "monotonic": False,
                "trend_tolerance": 0.08,
            }
        ]
    else:
        return {"ok": False, "detected": False, "issues": ["unknown_mutation"]}

    semantic = evaluate_recomposition_semantics(ir, mutated_plan)
    mathematics = evaluate_mathematical_invariants(ir, mutated_plan)
    ranking = rank_geometry_ir_candidates([ir], mutated_plan)
    issues = {
        str(item.get("type")) for item in [*semantic.get("errors", []), *mathematics.get("errors", [])]
    }
    for candidate in ranking.get("candidates", []):
        issues.update(str(item).split(":", 1)[-1] for item in candidate.get("hard_failures", []))
        for check in candidate.get("details", {}).get("transform_text", {}).get("checks", []):
            if check.get("contradictions"):
                issues.add("transform_text_conflict")
    expected = {str(item) for item in case.get("expected_issues", [])}
    detected = bool(expected & issues)
    return {
        "ok": detected,
        "detected": detected,
        "case_id": case.get("id"),
        "expected_issues": sorted(expected),
        "issues": sorted(issues),
        "semantic_ok": semantic.get("ok"),
        "mathematics_ok": mathematics.get("ok"),
        "ranking_ok": ranking.get("ok"),
    }
