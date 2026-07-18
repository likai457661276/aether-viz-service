"""Contract tests for local design-gap seeds of candidate IR families."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from evals.run_ir_routing_eval import run_route

DATASET_DIR = Path(__file__).parents[2] / "evals" / "datasets" / "ir_candidates"
EXPECTED_FAMILIES = {
    "geometric_constraint_scene",
    "distribution_chart_scene",
}


def _rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(DATASET_DIR.glob("*_failures.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


def test_candidate_failure_datasets_are_complete_and_langsmith_compatible() -> None:
    rows = _rows()
    case_ids = [row["metadata"]["case_id"] for row in rows]
    families = {row["metadata"]["candidate_family"] for row in rows}

    assert len(rows) == 10
    assert len(case_ids) == len(set(case_ids))
    assert families == EXPECTED_FAMILIES
    assert all(row["metadata"]["source"] == "design_gap_seed" for row in rows)
    assert all(row.get("inputs") and row.get("outputs") for row in rows)
    assert all(row["outputs"]["target_backend"] == row["metadata"]["candidate_family"] for row in rows)
    assert all(len(row["outputs"]["required_capabilities"]) >= 5 for row in rows)


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["metadata"]["case_id"])
def test_candidate_failure_is_an_observable_current_routing_gap(row: dict) -> None:
    registered = {backend.key for backend in DEFAULT_IR_REGISTRY.backends()}
    target = row["outputs"]["target_backend"]
    actual = run_route(row["inputs"])["selected_backend"]

    assert target not in registered
    assert row["outputs"]["current_expected_backend"] is None
    assert actual is row["outputs"]["current_expected_backend"]
