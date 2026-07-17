#!/usr/bin/env python3
"""Run local-only Edit HTML diagnosis and end-to-end evaluations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.evaluators.edit_html import (
    browser_runtime_evaluator,
    change_intent_satisfaction_evaluator,
    diagnosis_claim_bindability_evaluator,
    diagnosis_hard_change_coverage_evaluator,
    diagnosis_impact_coverage_evaluator,
    diagnosis_strategy_evaluator,
    edit_relevance_judge_evaluator,
    html_validation_evaluator,
    post_repair_intent_evaluator,
    preserve_satisfaction_evaluator,
    teaching_semantics_judge_evaluator,
    visual_quality_judge_evaluator,
)
from evals.targets.edit_html import load_examples, run_diagnosis_case, run_end_to_end_case

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIAGNOSIS_DATASET = ROOT / "evals/datasets/edit_html/diagnosis.jsonl"
DEFAULT_END_TO_END_DATASET = ROOT / "evals/datasets/edit_html/end_to_end.jsonl"
DEFAULT_OUTPUT = ROOT / "evals/reports/edit-html/latest"

Evaluator = Callable[[Any, Any], dict[str, Any]]


def _score(result: dict[str, Any], example: dict[str, Any], evaluators: tuple[Evaluator, ...]) -> dict[str, Any]:
    run = {"outputs": result}
    return {evaluator.__name__: evaluator(run, example) for evaluator in evaluators}


def run_evaluation(
    diagnosis_examples: list[dict[str, Any]],
    end_to_end_examples: list[dict[str, Any]],
    *,
    live_model: bool,
    browser: bool,
    judge: bool,
    max_runs: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    diagnosis_evaluators = (
        diagnosis_strategy_evaluator,
        diagnosis_impact_coverage_evaluator,
        diagnosis_hard_change_coverage_evaluator,
        diagnosis_claim_bindability_evaluator,
    )
    end_to_end_evaluators: tuple[Evaluator, ...] = (
        change_intent_satisfaction_evaluator,
        preserve_satisfaction_evaluator,
        html_validation_evaluator,
        post_repair_intent_evaluator,
    )
    if browser:
        end_to_end_evaluators += (browser_runtime_evaluator,)
    if judge:
        end_to_end_evaluators += (
            teaching_semantics_judge_evaluator,
            visual_quality_judge_evaluator,
            edit_relevance_judge_evaluator,
        )

    scheduled = [
        *(("diagnosis", example) for example in diagnosis_examples),
        *(("end_to_end", example) for example in end_to_end_examples),
    ]
    if max_runs is not None:
        scheduled = scheduled[:max_runs]
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for dataset_type, example in scheduled:
        if dataset_type == "diagnosis":
            result = run_diagnosis_case(example, live_model=live_model)
            scores = _score(result, example, diagnosis_evaluators)
        else:
            result = run_end_to_end_case(
                example,
                live_model=live_model,
                browser=browser,
                judge=judge,
            )
            scores = _score(result, example, end_to_end_evaluators)
        failed_metrics = sorted(name for name, value in scores.items() if value.get("score") != 1)
        record = {
            "id": example["id"],
            "dataset_type": dataset_type,
            "scores": scores,
            "failed_metrics": failed_metrics,
        }
        records.append(record)
        if failed_metrics:
            failures.append(record)
        print(json.dumps({"id": example["id"], "scores": scores}, ensure_ascii=False), flush=True)

    metric_names = sorted({name for record in records for name in record["scores"]})
    totals = {
        name: {
            "passed": sum(record["scores"].get(name, {}).get("score") == 1 for record in records),
            "total": sum(name in record["scores"] for record in records),
        }
        for name in metric_names
    }
    for value in totals.values():
        value["rate"] = round(value["passed"] / value["total"], 6) if value["total"] else 0.0
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "local_only": True,
        "mode": "live_model" if live_model else "deterministic_scaffold",
        "browser": browser,
        "llm_judge": judge,
        "diagnosis_example_count": len(diagnosis_examples),
        "end_to_end_example_count": len(end_to_end_examples),
        "run_count": len(records),
        "totals": totals,
        "failure_count": len(failures),
        "passed": bool(records) and not failures,
    }
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis-dataset", type=Path, default=DEFAULT_DIAGNOSIS_DATASET)
    parser.add_argument("--end-to-end-dataset", type=Path, default=DEFAULT_END_TO_END_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--suite", choices=("all", "diagnosis", "end-to-end"), default="all")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--judge", action="store_true")
    args = parser.parse_args()
    if args.max_runs is not None and args.max_runs < 1:
        parser.error("--max-runs 必须大于 0")
    if (args.browser or args.judge) and not args.live_model:
        parser.error("--browser/--judge 仅用于 --live-model 风险抽样")

    diagnosis_examples = load_examples(args.diagnosis_dataset) if args.suite in {"all", "diagnosis"} else []
    end_to_end_examples = load_examples(args.end_to_end_dataset) if args.suite in {"all", "end-to-end"} else []
    if (args.browser or args.judge) and not end_to_end_examples:
        parser.error("--browser/--judge 需要 --suite end-to-end 或 all")
    summary, failures = run_evaluation(
        diagnosis_examples,
        end_to_end_examples,
        live_model=args.live_model,
        browser=args.browser,
        judge=args.judge,
        max_runs=args.max_runs,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "latest-summary.json"
    failures_path = args.output_dir / "failures.jsonl"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in failures),
        encoding="utf-8",
    )
    print(json.dumps({"passed": summary["passed"], "summary": str(summary_path)}, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
