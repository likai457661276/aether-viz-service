"""Tests for the local, all-backend IR routing regression set."""

from __future__ import annotations

from evals.run_ir_routing_eval import DEFAULT_DATASET, evaluate_rows, load_rows, run_route


def _rows() -> list[dict]:
    return load_rows(DEFAULT_DATASET)


def test_ir_routing_dataset_covers_every_registered_backend() -> None:
    report = evaluate_rows(_rows())

    assert report["backend_coverage"]["ok"], report["backend_coverage"]
    assert report["ok"], report["results"]


def test_ir_routing_runner_uses_structured_plan_when_present() -> None:
    parametric = next(row for row in _rows() if "parametric_geometry" in row.get("tags", []))

    output = run_route(parametric["inputs"])

    assert output["selected_backend"] == "parametric_geometry_scene"
