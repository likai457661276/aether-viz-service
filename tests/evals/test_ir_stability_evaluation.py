"""Tests for IR stability failure-mode datasets and temperature A/B harness."""

from __future__ import annotations

import json
from pathlib import Path

from evals.datasets.build_ir_stability_regression import build_candidates
from evals.datasets.ir_stability.taxonomy import required_coverage
from evals.run_ir_stability_eval import evaluate_rows, load_rows
from evals.run_scene_temperature_ab import run_ab

DATASET = Path(__file__).parents[2] / "evals" / "datasets" / "ir_stability" / "failure_modes.jsonl"


def test_ir_stability_dataset_covers_required_matrix() -> None:
    rows = load_rows(DATASET)
    report = evaluate_rows(rows)
    assert report["ok"], report
    assert report["passed"] == report["total"] >= len(required_coverage())
    assert report["coverage"]["missing"] == []


def test_build_ir_stability_candidates_from_local_failure_blob(tmp_path: Path) -> None:
    path = tmp_path / "failures.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "trace-1",
                "topic": "参数联动演示",
                "ok": False,
                "generation_backend": "linked_coordinate_scene",
                "final_hard_failures": ["schema:linked_coordinate_ir_parse"],
                "plan": {
                    "interactive_type": "simulation",
                    "knowledge_profile": {"representation_type": "linked_coordinate_scene"},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    rows = build_candidates([path])
    assert len(rows) == 1
    assert rows[0]["metadata"]["pending_review"] is True
    assert rows[0]["metadata"]["failure_mode"] == "schema_or_parse"
    assert rows[0]["outputs"] == {}


def test_scene_temperature_ab_dry_run() -> None:
    report = run_ab(
        topics=[{"topic": "切分重排面积守恒", "plan": {}}],
        temperatures=[0.0, 0.05],
        live_model=False,
    )
    assert report["ok"] is True
    assert report["dry_run"] is True
    assert report["temperatures"] == [0.0, 0.05]
