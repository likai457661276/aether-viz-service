"""Contract tests for local design-gap seeds of candidate IR families."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from evals.run_ir_routing_eval import run_route

DATASET_DIR = Path(__file__).parents[2] / "evals" / "datasets" / "ir_candidates"
EXPECTED_FAMILIES = {
    "distribution_chart_scene",
}
# Remaining gaps require continuous density / sampling capabilities beyond
# the deterministic data_distribution IR family.
OPEN_GAP_CASES = {
    "distribution-binomial-parameters",
    "distribution-normal-density",
    "distribution-sampling-mean",
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

    assert len(rows) == 3
    assert set(case_ids) == OPEN_GAP_CASES
    assert families == EXPECTED_FAMILIES
    assert all(row["metadata"]["source"] == "design_gap_seed" for row in rows)
    assert all(row.get("inputs") and row.get("outputs") for row in rows)
    assert all(row["outputs"]["target_backend"] == row["metadata"]["candidate_family"] for row in rows)
    assert all(len(row["outputs"]["required_capabilities"]) >= 5 for row in rows)


@pytest.mark.parametrize("row", _rows(), ids=lambda row: row["metadata"]["case_id"])
def test_candidate_seed_remains_an_observable_routing_gap(row: dict) -> None:
    registered = {backend.key for backend in DEFAULT_IR_REGISTRY.backends()}
    target = row["outputs"]["target_backend"]
    actual = run_route(row["inputs"])["selected_backend"]

    assert target not in registered
    assert row["outputs"]["current_expected_backend"] is None
    assert actual is None
    assert row["metadata"]["case_id"] in OPEN_GAP_CASES
