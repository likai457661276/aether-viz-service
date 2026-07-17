from __future__ import annotations

import json
from pathlib import Path

from aetherviz_service.aetherviz.contracts.html_stream import HtmlStreamResult
from aetherviz_service.aetherviz.contracts.pipeline import _summarize_sse_trace, run_html_pipeline
from aetherviz_service.aetherviz.edit.context import build_edit_assembly_plan
from aetherviz_service.aetherviz.edit.workflow import _summarize_edit_stream
from evals.run_edit_html_eval import run_evaluation
from evals.targets.edit_html import load_examples, run_diagnosis_case

ROOT = Path(__file__).resolve().parents[2]
DIAGNOSIS_DATASET = ROOT / "evals/datasets/edit_html/diagnosis.jsonl"
END_TO_END_DATASET = ROOT / "evals/datasets/edit_html/end_to_end.jsonl"
BASELINE = ROOT / "evals/datasets/edit_html/fixtures/baseline.html"


def test_edit_html_dataset_has_observed_single_step_output_shape() -> None:
    example = load_examples(DIAGNOSIS_DATASET)[0]
    output = run_diagnosis_case(example, live_model=False)

    assert set(output) == {"diagnosis", "baseline_html"}
    assert isinstance(output["diagnosis"]["change_checks"], list)
    assert output["diagnosis"]["strategy"] == "full_html_regeneration"


def test_edit_html_deterministic_dataset_and_evaluators_pass() -> None:
    summary, failures = run_evaluation(
        load_examples(DIAGNOSIS_DATASET),
        load_examples(END_TO_END_DATASET),
        live_model=False,
        browser=False,
        judge=False,
    )

    assert summary["local_only"] is True
    assert summary["run_count"] == 11
    assert summary["passed"] is True
    assert failures == []


def test_edit_stream_and_final_sse_keep_intent_metadata(monkeypatch) -> None:
    html = BASELINE.read_text(encoding="utf-8")
    plan = build_edit_assembly_plan(html, "匀速运动")
    result = HtmlStreamResult(
        html=html,
        degraded=False,
        strategy="full_html_regeneration",
        intent_passed=True,
        intent_soft_failed=("soft_visual",),
        intent_check_count=3,
        intent_summary="intent_ok",
    )
    monkeypatch.setattr(
        "aetherviz_service.aetherviz.contracts.pipeline.settings.aetherviz_max_repair_attempts",
        0,
    )

    chunks = list(
        run_html_pipeline(
            run_id="edit-eval-metadata",
            phase="edit_html",
            start_event="html.edit_started",
            topic="匀速运动",
            plan=plan,
            html_stream_factory=lambda: iter([result]),
            emit_start_event=False,
        )
    )
    summary = _summarize_sse_trace(chunks)
    stream_summary = _summarize_edit_stream([result])
    done = next(
        json.loads(line[6:])
        for chunk in chunks
        for line in chunk.splitlines()
        if line.startswith("data: ") and '"html"' in line
    )
    metadata = done["data"]["metadata"]

    assert metadata["intent_passed"] is True
    assert metadata["intent_soft_failed"] == ["soft_visual"]
    assert metadata["intent_check_count"] == 3
    assert summary["final"]["intent_summary"] == "intent_ok"
    assert stream_summary["intent_passed"] is True
    assert stream_summary["intent_check_count"] == 3
