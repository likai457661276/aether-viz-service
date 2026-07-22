#!/usr/bin/env python3
"""Run the local-only cross-dimensional recomposition evaluation."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aetherviz_service.aetherviz.ir.recomposition.contract import build_deterministic_geometry_ir
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from evals.evaluators.completion import evaluate_completion_case, evaluate_feasibility_case
from evals.evaluators.deterministic import (
    diagnostic_alignment,
    evaluate_run,
    validate_dataset_matrix,
)
from evals.evaluators.teaching_semantics import evaluate_invalid_case
from evals.targets.recomposition import (
    build_evaluation_plan_seed,
    load_completion_cases,
    load_examples,
    load_feasibility_cases,
    run_case,
    run_completion_case,
    run_feasibility_case,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "evals/datasets/recomposition"
DEFAULT_DATASET = DEFAULT_FIXTURES / "dataset.jsonl"
DEFAULT_COMPLETION_CASES = DEFAULT_FIXTURES / "completion_cases"
DEFAULT_FEASIBILITY_CASES = DEFAULT_FIXTURES / "feasibility_cases"
DEFAULT_INVALID_CASES = DEFAULT_FIXTURES / "invalid_cases"
DEFAULT_THRESHOLDS = DEFAULT_FIXTURES / "expected/thresholds.json"
DEFAULT_OUTPUT = ROOT / "evals/reports/latest"


def run_evaluation(
    examples: list[dict[str, Any]],
    *,
    repetitions: int,
    live_model: bool,
    browser: bool,
    max_runs: int | None,
    completion_cases_path: Path,
    invalid_cases_path: Path,
    thresholds_path: Path,
    workers: int = 1,
    feasibility_cases_path: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    matrix = validate_dataset_matrix(examples)
    if not matrix["ok"]:
        raise ValueError(f"dataset_matrix_invalid:{matrix['errors']}")
    thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))
    runs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    scheduled = [
        (repetition, example)
        for repetition in range(1, repetitions + 1)
        for example in examples
    ]
    if max_runs is not None:
        scheduled = scheduled[:max_runs]

    def execute(item: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any], dict[str, Any]]:
        repetition, example = item
        return repetition, example, run_case(example, live_model=live_model, browser=browser)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        completed = executor.map(execute, scheduled)
        for repetition, example, result in completed:
            scores = evaluate_run(result, example, live_model=live_model, browser_enabled=browser)
            alignment = diagnostic_alignment(result, example)
            record = {
                "id": example["id"],
                "topic": result["topic"],
                "repetition": repetition,
                "scores": scores,
                "diagnostic_alignment": alignment,
                "fallback": result["fallback"],
                "repaired": result["repaired"],
                "candidate_ranking_report": result["candidate_ranking_report"],
                "geometry_ir_facts": result["geometry_ir_facts"],
            }
            runs.append(record)
            failed_metrics = sorted(name for name, passed in scores.items() if not passed)
            if failed_metrics:
                failures.append({**record, "failed_metrics": failed_metrics})
            print(
                json.dumps(
                    {"id": example["id"], "repetition": repetition, "scores": scores},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    invalid_results = _run_invalid_cases(examples[0], invalid_cases_path)
    invalid_failures = [item for item in invalid_results if not item["ok"]]
    failures.extend({"kind": "invalid_case", **item} for item in invalid_failures)
    completion_results = _run_completion_cases(completion_cases_path)
    completion_summary = _completion_summary(completion_results, thresholds)
    completion_failures = [item for item in completion_results if not item["ok"]]
    failures.extend({"kind": "completion_case", **item} for item in completion_failures)
    feasibility_path = feasibility_cases_path or DEFAULT_FEASIBILITY_CASES
    feasibility_results = _run_feasibility_cases(feasibility_path)
    feasibility_summary = _feasibility_summary(feasibility_results, thresholds)
    feasibility_failures = [item for item in feasibility_results if not item["ok"]]
    failures.extend({"kind": "feasibility_case", **item} for item in feasibility_failures)
    metric_names = sorted({name for run in runs for name in run["scores"]})
    totals = {
        name: {
            "passed": sum(bool(run["scores"].get(name)) for run in runs),
            "total": len(runs),
            "rate": round(sum(bool(run["scores"].get(name)) for run in runs) / len(runs), 6),
            "threshold": float(thresholds[name]),
        }
        for name in metric_names
    }
    run_range_ok = max_runs is not None or 72 <= len(runs) <= 90
    passed = (
        matrix["ok"]
        and run_range_ok
        and not invalid_failures
        and completion_summary["ok"]
        and feasibility_summary["ok"]
        and all(item["rate"] >= item["threshold"] for item in totals.values())
    )
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "local_only": True,
        "mode": "live_model" if live_model else "deterministic_scaffold",
        "browser": browser,
        "example_count": len(examples),
        "repetitions": repetitions,
        "run_count": len(runs),
        "expected_run_range": [72, 90],
        "run_range_ok": run_range_ok,
        "matrix": matrix,
        "totals": totals,
        "invalid_cases": {
            "passed": len(invalid_results) - len(invalid_failures),
            "total": len(invalid_results),
            "results": invalid_results,
        },
        "completion_cases": completion_summary,
        "feasibility_cases": feasibility_summary,
        "diagnostic_alignment": _alignment_summary(runs),
        "generation_strategies": _generation_strategy_summary(runs),
        "failure_count": len(failures),
        "passed": passed,
    }
    return summary, failures


def _run_invalid_cases(example: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    plan = normalize_plan(build_evaluation_plan_seed(example), str(example["inputs"]["topic"]))
    base_ir = build_deterministic_geometry_ir(plan)
    return [
        evaluate_invalid_case(base_ir, plan, json.loads(case_path.read_text(encoding="utf-8")))
        for case_path in sorted(path.glob("*.json"))
    ]


def _run_completion_cases(path: Path) -> list[dict[str, Any]]:
    return [
        evaluate_completion_case(run_completion_case(example), example)
        for example in load_completion_cases(path)
    ]


def _run_feasibility_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        evaluate_feasibility_case(run_feasibility_case(example), example)
        for example in load_feasibility_cases(path)
    ]


def _completion_summary(results: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    bounds_results = [
        item for item in results if item.get("strategy") == "deterministic_target_bounds_completion"
    ]
    attempts = sum(int(item.get("attempts", 0)) for item in bounds_results)
    successes = sum(int(item.get("successes", 0)) for item in bounds_results)
    success_rate = successes / attempts if attempts else 0.0
    minimum_attempts = int(thresholds["target_bounds_completion_min_attempts"])
    required_success_rate = float(thresholds["target_bounds_completion_success_rate"])
    construction_passed = sum(
        1 for item in results if item.get("pipeline") == "construction" and item.get("ok")
    )
    construction_total = sum(1 for item in results if item.get("pipeline") == "construction")
    composite_results = [item for item in results if item.get("pipeline") != "construction"]
    composite_passed = sum(1 for item in composite_results if item.get("ok"))
    composite_total = len(composite_results)
    return {
        "ok": (
            bool(results)
            and all(item.get("ok") for item in results)
            and attempts >= minimum_attempts
            and success_rate >= required_success_rate
            and construction_passed >= int(thresholds.get("construction_min_passed", 0))
            and composite_passed >= int(thresholds.get("composite_min_passed", 0))
        ),
        "passed": sum(bool(item.get("ok")) for item in results),
        "total": len(results),
        "target_bounds_completion_attempts": attempts,
        "target_bounds_completion_successes": successes,
        "target_bounds_completion_success_rate": round(success_rate, 6),
        "required_min_attempts": minimum_attempts,
        "required_success_rate": required_success_rate,
        "construction_passed": construction_passed,
        "construction_total": construction_total,
        "composite_passed": composite_passed,
        "composite_total": composite_total,
        "results": results,
    }


def _feasibility_summary(results: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    minimum_passed = int(thresholds.get("feasibility_min_passed", 1 if results else 0))
    passed = sum(bool(item.get("ok")) for item in results)
    return {
        "ok": (
            (not results and minimum_passed == 0)
            or (bool(results) and passed >= minimum_passed and all(item.get("ok") for item in results))
        ),
        "passed": passed,
        "total": len(results),
        "required_min_passed": minimum_passed,
        "results": results,
    }


def _alignment_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    names = ("piece_count", "primary_transform", "stage_count")
    return {
        name: {
            "matched": sum(run["diagnostic_alignment"][name] for run in runs),
            "total": len(runs),
        }
        for name in names
    }


def _generation_strategy_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    reports = [
        run["candidate_ranking_report"]
        for run in runs
        if run.get("candidate_ranking_report", {}).get("strategy")
    ]
    strategies: dict[str, int] = {}
    bounds_attempts = 0
    bounds_successes = 0
    completion_attempts = 0
    completion_successes = 0
    scale_attempts = 0
    scale_successes = 0
    construction_ok = 0
    construction_changed = 0
    completed_stage_counts: dict[str, int] = {}
    for report in reports:
        strategy = str(report.get("strategy"))
        strategies[strategy] = strategies.get(strategy, 0) + 1
        for completion in report.get("target_bounds_completion", []):
            if not isinstance(completion, dict) or not completion.get("attempted"):
                continue
            bounds_attempts += 1
            bounds_successes += int(bool(completion.get("ok")))
        for completion in report.get("waypoint_completion", []):
            if not isinstance(completion, dict) or not completion.get("attempted"):
                continue
            completion_attempts += 1
            completion_successes += int(bool(completion.get("ok")))
            for stage_id in completion.get("completed_stage_ids", []):
                name = str(stage_id)
                completed_stage_counts[name] = completed_stage_counts.get(name, 0) + 1
        for completion in report.get("footprint_scale_completion", []):
            if not isinstance(completion, dict) or not completion.get("attempted"):
                continue
            scale_attempts += 1
            scale_successes += int(bool(completion.get("ok")))
        for item in report.get("construction_materialization", []):
            if not isinstance(item, dict):
                continue
            construction_ok += int(bool(item.get("ok")))
            construction_changed += int(bool(item.get("changed")))
    return {
        "observed_runs": len(reports),
        "counts": dict(sorted(strategies.items())),
        "target_bounds_candidate_attempts": bounds_attempts,
        "target_bounds_candidate_successes": bounds_successes,
        "waypoint_candidate_attempts": completion_attempts,
        "waypoint_candidate_successes": completion_successes,
        "footprint_scale_candidate_attempts": scale_attempts,
        "footprint_scale_candidate_successes": scale_successes,
        "construction_materialization_ok": construction_ok,
        "construction_materialization_changed": construction_changed,
        "completed_stage_counts": dict(sorted(completed_stage_counts.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--completion-cases", type=Path, default=DEFAULT_COMPLETION_CASES)
    parser.add_argument("--feasibility-cases", type=Path, default=DEFAULT_FEASIBILITY_CASES)
    parser.add_argument("--invalid-cases", type=Path, default=DEFAULT_INVALID_CASES)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="本地生成并发数；默认 1，真实模型批量回归可显式提高",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions 必须大于 0")
    if args.max_runs is not None and args.max_runs < 1:
        parser.error("--max-runs 必须大于 0")
    if not 1 <= args.workers <= 4:
        parser.error("--workers 必须在 1 到 4 之间")
    examples = load_examples(args.dataset)
    summary, failures = run_evaluation(
        examples,
        repetitions=args.repetitions,
        live_model=args.live_model,
        browser=args.browser,
        max_runs=args.max_runs,
        completion_cases_path=args.completion_cases,
        invalid_cases_path=args.invalid_cases,
        thresholds_path=args.thresholds,
        workers=args.workers,
        feasibility_cases_path=args.feasibility_cases,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "latest-summary.json"
    failures_path = args.output_dir / "failures.jsonl"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in failures), encoding="utf-8"
    )
    print(
        json.dumps(
            {"passed": summary["passed"], "summary": str(summary_path), "failures": str(failures_path)},
            ensure_ascii=False,
        )
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
