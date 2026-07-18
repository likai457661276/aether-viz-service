"""Tests for local generate-pipeline baseline eval (no live model)."""

from __future__ import annotations

from pathlib import Path

from aetherviz_service.aetherviz.contracts.repair.session import REPAIR_STRATEGY_ORDER, RepairSession
from evals.run_generate_baseline_eval import _load_rows, run_evaluation, run_repair_case

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals/datasets/generate_baseline/pipeline_core.jsonl"


def test_generate_baseline_eval_passes_locally() -> None:
    report = run_evaluation(DATASET)
    assert report["local_only"] is True
    assert report["live_model"] is False
    assert report["ok"] is True
    assert report["total"] == 8
    assert report["baselines"]["route"]["passed"] == report["baselines"]["route"]["total"]
    assert report["baselines"]["hard_validation"]["passed"] == report["baselines"]["hard_validation"]["total"]
    assert report["baselines"]["repair"]["passed"] == report["baselines"]["repair"]["total"]


def test_repair_session_is_bounded_and_ordered() -> None:
    session = RepairSession(max_model_attempts=2)
    assert session.max_model_attempts == 2
    assert REPAIR_STRATEGY_ORDER == ("deterministic", "function-model", "model")


def test_repair_baseline_runs_complete_pipeline_and_emits_done() -> None:
    repair_row = next(row for row in _load_rows(DATASET) if row["suite"] == "repair")
    output = run_repair_case(repair_row["inputs"])

    assert output["repaired_ok"] is True
    assert output["repair_event_strategies"] == ["deterministic"]
    assert "html.done" in output["event_names"]
    assert "error" not in output["event_names"]
