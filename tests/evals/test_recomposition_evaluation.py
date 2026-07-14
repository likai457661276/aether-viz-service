from __future__ import annotations

import json
from pathlib import Path

from aetherviz_service.aetherviz.tools.recomposition_ir import build_deterministic_geometry_ir
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from evals.evaluators.completion import evaluate_completion_case
from evals.evaluators.deterministic import REQUIRED_DIMENSIONS, validate_dataset_matrix
from evals.evaluators.teaching_semantics import evaluate_invalid_case
from evals.run_eval import (
    DEFAULT_COMPLETION_CASES,
    DEFAULT_DATASET,
    DEFAULT_INVALID_CASES,
    DEFAULT_THRESHOLDS,
    run_evaluation,
)
from evals.targets.recomposition import (
    build_evaluation_plan_seed,
    load_completion_cases,
    load_examples,
    run_completion_case,
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


def test_target_bounds_completion_fixture_exercises_repair_branch() -> None:
    cases = load_completion_cases(DEFAULT_COMPLETION_CASES)
    assert len(cases) == 1

    result = run_completion_case(cases[0])
    evaluation = evaluate_completion_case(result, cases[0])

    assert evaluation["ok"], evaluation
    assert evaluation["attempts"] == 1
    assert evaluation["success_rate"] == 1.0
    assert evaluation["strategy"] == "deterministic_target_bounds_completion"

    rejected = evaluate_completion_case(
        {
            **result,
            "strategy": "raw_candidate",
            "completion_reports": [],
            "final_ranking_ok": False,
        },
        cases[0],
    )
    assert rejected["ok"] is False
    assert rejected["checks"]["minimum_attempts"] is False
    assert rejected["checks"]["completion_success_rate"] is False


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
    )
    assert summary["local_only"] is True
    assert summary["passed"] is True
    assert summary["run_count"] == 2
    assert summary["completion_cases"]["ok"] is True
    assert summary["completion_cases"]["target_bounds_completion_attempts"] == 1
    assert summary["completion_cases"]["target_bounds_completion_success_rate"] == 1.0
    assert summary["generation_strategies"] == {
        "observed_runs": 0,
        "counts": {},
        "target_bounds_candidate_attempts": 0,
        "target_bounds_candidate_successes": 0,
        "waypoint_candidate_attempts": 0,
        "waypoint_candidate_successes": 0,
        "completed_stage_counts": {},
    }
    assert failures == []
