from __future__ import annotations

import json
from pathlib import Path

from aetherviz_service.aetherviz.ir.recomposition.contract import build_deterministic_geometry_ir
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from evals.evaluators.completion import evaluate_completion_case, evaluate_feasibility_case
from evals.evaluators.deterministic import REQUIRED_DIMENSIONS, validate_dataset_matrix
from evals.evaluators.teaching_semantics import evaluate_invalid_case
from evals.run_eval import (
    DEFAULT_COMPLETION_CASES,
    DEFAULT_DATASET,
    DEFAULT_FEASIBILITY_CASES,
    DEFAULT_INVALID_CASES,
    DEFAULT_THRESHOLDS,
    run_evaluation,
)
from evals.targets.recomposition import (
    build_evaluation_plan_seed,
    load_completion_cases,
    load_examples,
    load_feasibility_cases,
    run_completion_case,
    run_feasibility_case,
)


def test_local_recomposition_dataset_covers_requested_matrix() -> None:
    examples = load_examples(DEFAULT_DATASET)
    report = validate_dataset_matrix(examples)
    assert report["ok"], report["errors"]
    assert len(examples) == 24
    for name, values in REQUIRED_DIMENSIONS.items():
        assert set(report["coverage"][name]) == {str(value) for value in values}


def test_all_invalid_recomposition_cases_are_detected() -> None:
    example = load_examples(DEFAULT_DATASET)[0]
    plan = normalize_plan(build_evaluation_plan_seed(example), example["inputs"]["topic"])
    ir = build_deterministic_geometry_ir(plan)
    results = [
        evaluate_invalid_case(ir, plan, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(DEFAULT_INVALID_CASES.glob("*.json"))
    ]
    assert len(results) == 5
    assert all(result["ok"] for result in results), results


def test_completion_and_feasibility_fixtures_cover_new_stages() -> None:
    cases = load_completion_cases(DEFAULT_COMPLETION_CASES)
    assert {case["id"] for case in cases} == {
        "composite-waypoint-with-assembly-failure",
        "construction-attach-edge-rect-pair",
        "target-assembly-out-of-bounds",
    }
    evaluations = [evaluate_completion_case(run_completion_case(case), case) for case in cases]
    assert all(item["ok"] for item in evaluations), evaluations

    bounds = next(item for item in evaluations if item["case_id"] == "target-assembly-out-of-bounds")
    assert bounds["strategy"] == "deterministic_target_bounds_completion"
    assert bounds["attempts"] == 1
    assert bounds["success_rate"] == 1.0

    composite = next(
        item for item in evaluations if item["case_id"] == "composite-waypoint-with-assembly-failure"
    )
    assert composite["strategy"] == "deterministic_waypoint_completion"
    assert composite["final_hard_failures"] == ["assembly:target_assembly_failed"]

    construction = next(
        item for item in evaluations if item["case_id"] == "construction-attach-edge-rect-pair"
    )
    assert construction["pipeline"] == "construction"
    assert construction["strategy"] == "construction_materialization"

    feasibility_cases = load_feasibility_cases(DEFAULT_FEASIBILITY_CASES)
    assert len(feasibility_cases) == 1
    feasibility = evaluate_feasibility_case(run_feasibility_case(feasibility_cases[0]), feasibility_cases[0])
    assert feasibility["ok"], feasibility
    assert feasibility["error_types"] == ["expanded_piece_budget_exceeded"]


def test_local_evaluation_smoke_is_network_independent(tmp_path: Path) -> None:
    examples = load_examples(DEFAULT_DATASET)
    summary, failures = run_evaluation(
        examples,
        repetitions=1,
        live_model=False,
        browser=False,
        max_runs=2,
        completion_cases_path=DEFAULT_COMPLETION_CASES,
        invalid_cases_path=DEFAULT_INVALID_CASES,
        thresholds_path=DEFAULT_THRESHOLDS,
        feasibility_cases_path=DEFAULT_FEASIBILITY_CASES,
    )
    assert summary["local_only"] is True
    assert summary["passed"] is True
    assert summary["run_count"] == 2
    assert summary["completion_cases"]["ok"] is True
    assert summary["completion_cases"]["target_bounds_completion_attempts"] == 1
    assert summary["completion_cases"]["target_bounds_completion_success_rate"] == 1.0
    assert summary["completion_cases"]["construction_passed"] == 1
    assert summary["completion_cases"]["composite_passed"] == 2
    assert summary["feasibility_cases"]["ok"] is True
    assert summary["feasibility_cases"]["passed"] == 1
    assert summary["generation_strategies"] == {
        "observed_runs": 0,
        "counts": {},
        "target_bounds_candidate_attempts": 0,
        "target_bounds_candidate_successes": 0,
        "waypoint_candidate_attempts": 0,
        "waypoint_candidate_successes": 0,
        "footprint_scale_candidate_attempts": 0,
        "footprint_scale_candidate_successes": 0,
        "construction_materialization_ok": 0,
        "construction_materialization_changed": 0,
        "completed_stage_counts": {},
    }
    assert failures == []
