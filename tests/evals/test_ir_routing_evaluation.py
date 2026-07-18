"""Tests for the local, all-backend IR routing regression set."""

from __future__ import annotations

import json
from pathlib import Path

from evals.datasets.build_ir_routing_regression import build_candidates, is_disagreement
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


def test_evaluate_rows_tolerates_legacy_and_enriched_route_payloads() -> None:
    legacy = [
        {
            "inputs": {"topic": "圆的标准方程与图像"},
            "outputs": {"selected_backend": "coordinate_graph_scene"},
            "tags": ["legacy"],
        }
    ]
    report = evaluate_rows(legacy)
    assert report["total"] == 1
    assert report["results"][0]["exact_match"] in {0, 1}

    enriched_output = run_route(legacy[0]["inputs"])
    assert "llm_selected_backend" in enriched_output
    assert "llm_confidence" in enriched_output
    assert "llm_required_capabilities" in enriched_output
    # evaluate_rows only reads selected_backend; extra keys must not break it.
    assert evaluate_rows(legacy)["total"] == 1


def test_build_ir_routing_regression_emits_pending_review_without_expected(tmp_path: Path) -> None:
    trace = {
        "trace_id": "trace-shadow-1",
        "topic": "单位圆与正弦曲线联动",
        "metadata": {
            "generation_backend": "linked_coordinate_scene",
            "generation_route_llm_invoked": True,
            "generation_route_llm_accepted": True,
            "generation_route_fallback": "shadow_mode",
            "generation_route_llm_selected_backend": None,
            "generation_route_llm_confidence": 0.91,
            "generation_route_llm_required_capabilities": ["multi_view", "shared_parameter"],
            "generation_route_candidates": [
                {
                    "backend_key": "linked_coordinate_scene",
                    "eligible": True,
                    "score": 0.96,
                    "matched_capabilities": ["multi_view"],
                    "missing_capabilities": [],
                    "exclusion_reasons": [],
                    "reasons": ["multi_view"],
                }
            ],
        },
    }
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")

    rows = build_candidates([path])

    assert len(rows) == 1
    assert rows[0]["outputs"]["selected_backend"] is None
    assert "pending_review" in rows[0]["tags"]
    assert rows[0]["metadata"]["deterministic_selected"] == "linked_coordinate_scene"
    assert rows[0]["metadata"]["llm_selected_backend"] is None
    assert rows[0]["metadata"]["fallback"] == "shadow_mode"
    assert is_disagreement(
        {
            "llm_invoked": True,
            "selected_backend": "linked_coordinate_scene",
            "llm_selected_backend": None,
            "fallback": "shadow_mode",
            "llm_accepted": True,
        }
    )


def test_build_ir_routing_regression_reads_langsmith_exported_root_run(tmp_path: Path) -> None:
    exported_run = {
        "run_id": "root-run-1",
        "trace_id": "trace-export-1",
        "name": "aetherviz.generate_workflow",
        "inputs": {"topic": "数轴上的不等式解集"},
        "outputs": {
            "final": {
                "event": "html.done",
                "generation_backend": "number_line_scene",
                "generation_route_source": "deterministic",
                "generation_route_llm_invoked": True,
                "generation_route_llm_accepted": True,
                "generation_route_fallback": "shadow_mode",
                "generation_route_llm_selected_backend": None,
                "generation_route_llm_confidence": 0.94,
                "generation_route_llm_required_capabilities": ["number_line", "inequality_ray"],
                "generation_route_candidates": [],
            }
        },
    }
    path = tmp_path / "trace-export.jsonl"
    path.write_text(json.dumps(exported_run, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = build_candidates([path])

    assert len(rows) == 1
    assert rows[0]["inputs"] == {"topic": "数轴上的不等式解集"}
    assert rows[0]["metadata"]["trace_id"] == "trace-export-1"
    assert rows[0]["metadata"]["deterministic_selected"] == "number_line_scene"
    assert rows[0]["metadata"]["llm_selected_backend"] is None


def test_shadow_agreement_is_not_mined_as_disagreement() -> None:
    assert not is_disagreement(
        {
            "llm_invoked": True,
            "selected_backend": "number_line_scene",
            "llm_selected_backend": "number_line_scene",
            "fallback": "shadow_mode",
            "llm_accepted": True,
        }
    )
    assert is_disagreement(
        {
            "llm_invoked": True,
            "selected_backend": "number_line_scene",
            "llm_selected_backend": "coordinate_graph_scene",
            "fallback": "shadow_mode",
            "llm_accepted": True,
        }
    )
    assert not is_disagreement(
        {
            "llm_invoked": True,
            "deterministic_observed": False,
            "selected_backend": None,
            "llm_selected_backend": "number_line_scene",
            "fallback": "judge_run_only",
        }
    )
