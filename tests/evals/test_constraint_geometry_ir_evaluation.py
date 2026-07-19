from __future__ import annotations

from evals.run_constraint_geometry_ir_eval import DEFAULT_DATASET, evaluate_rows, load_rows


def test_constraint_geometry_ir_failure_dataset_repairs_all_cases() -> None:
    rows = load_rows(DEFAULT_DATASET)

    report = evaluate_rows(rows)

    assert len(rows) == 4
    assert report["ok"], report["results"]
