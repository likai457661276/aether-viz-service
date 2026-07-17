"""Local generate-pipeline baselines: route hit, hard validation, deterministic repair.

Does not call live models or remote LangSmith Dataset/Evaluator APIs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aetherviz_service.aetherviz.contracts.html_stream import HtmlStreamResult
from aetherviz_service.aetherviz.contracts.layout import assemble_layout_contract
from aetherviz_service.aetherviz.contracts.pipeline import run_html_pipeline
from aetherviz_service.aetherviz.contracts.repair.deterministic import deterministic_can_address
from aetherviz_service.aetherviz.contracts.repair.session import REPAIR_STRATEGY_ORDER, RepairSession
from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings
from evals.evaluators.generate_baseline import hard_validation_pass, repair_success, route_hit

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "generate_baseline" / "pipeline_core.jsonl"
FIXTURES = Path(__file__).parent / "datasets" / "generate_baseline" / "fixtures"


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _sample_plan() -> dict[str, Any]:
    return normalize_plan(
        {
            "interactive_type": "simulation",
            "subject": "physics",
            "title": "基线课件",
            "goal": "验证装配与校验基线",
            "interactive_spec": {
                "type": "simulation",
                "concept": "基线",
                "variables": [{"name": "parameter", "label": "参数", "min": 0, "max": 100, "default": 50}],
            },
        },
        "基线",
    )


def run_route_case(inputs: dict[str, Any]) -> dict[str, Any]:
    topic = str(inputs.get("topic") or "")
    return resolve_generation_route(normalize_plan({}, topic)).as_dict()


def run_hard_validation_case(inputs: dict[str, Any]) -> dict[str, Any]:
    html = _fixture_html(str(inputs["fixture"]))
    plan = _sample_plan()
    model_html = html
    if inputs.get("assemble"):
        html = assemble_layout_contract(html, plan)
    report = build_validation_report(html, plan=plan, model_html=model_html)
    return {
        "ok": bool(report.get("ok")),
        "summary": report.get("summary"),
        "error_types": [str(item.get("type")) for item in report.get("errors", []) if isinstance(item, dict)],
    }


def run_repair_case(inputs: dict[str, Any]) -> dict[str, Any]:
    html = _fixture_html(str(inputs["fixture"]))
    plan = _sample_plan()
    report = build_validation_report(html, plan=plan, model_html=html)
    strategy = str(inputs.get("strategy") or "deterministic")
    if strategy != "deterministic":
        return {
            "repaired_ok": False,
            "strategy": strategy,
            "skipped": True,
            "reason": "live_model_repair_not_in_baseline",
            "repair_strategy_order": list(REPAIR_STRATEGY_ORDER),
            "session_max_attempts": RepairSession().max_model_attempts,
        }
    can_address = deterministic_can_address(report)
    if not can_address:
        return {
            "repaired_ok": False,
            "strategy": strategy,
            "can_address": False,
            "error_types": [str(item.get("type")) for item in report.get("errors", []) if isinstance(item, dict)],
        }
    with patch.object(settings, "aetherviz_max_repair_attempts", 0):
        chunks = list(
            run_html_pipeline(
                run_id="generate-baseline-repair",
                phase="generate",
                start_event="html.generation_started",
                topic="基线",
                plan=plan,
                html_stream_factory=lambda: iter([HtmlStreamResult(html=html, degraded=False)]),
                emit_start_event=False,
            )
        )
    events = [
        json.loads(line[6:])
        for chunk in chunks
        for line in chunk.splitlines()
        if line.startswith("data: ")
    ]
    done = next((event for event in events if event.get("event") == "html.done"), None)
    repair_events = [event for event in events if event.get("event") == "repair.done"]
    return {
        "repaired_ok": bool(done and done.get("data", {}).get("metadata", {}).get("repaired")),
        "strategy": strategy,
        "can_address": can_address,
        "before_ok": bool(report.get("ok")),
        "event_names": [str(event.get("event")) for event in events],
        "repair_event_strategies": [
            str(event.get("data", {}).get("strategy")) for event in repair_events
        ],
        "repair_strategy_order": list(REPAIR_STRATEGY_ORDER),
        "session_max_attempts": RepairSession().max_model_attempts,
    }


def evaluate_row(row: dict[str, Any]) -> dict[str, Any]:
    suite = str(row.get("suite") or "")
    if suite == "route":
        output = run_route_case(row["inputs"])
        score = route_hit({"outputs": output}, row)
        metric = "route_hit"
    elif suite == "hard_validation":
        output = run_hard_validation_case(row["inputs"])
        score = hard_validation_pass({"outputs": output}, row)
        metric = "hard_validation_pass"
    elif suite == "repair":
        output = run_repair_case(row["inputs"])
        score = repair_success({"outputs": output}, row)
        metric = "repair_success"
    else:
        raise ValueError(f"unknown_suite:{suite}")
    return {
        "suite": suite,
        "metric": metric,
        "tags": row.get("tags", []),
        "inputs": row.get("inputs"),
        "expected": row.get("outputs"),
        "actual": output,
        "score": score["score"],
        "comment": score["comment"],
    }


def run_evaluation(dataset: Path = DEFAULT_DATASET) -> dict[str, Any]:
    rows = _load_rows(dataset)
    results = [evaluate_row(row) for row in rows]
    by_suite: dict[str, dict[str, Any]] = {}
    for item in results:
        bucket = by_suite.setdefault(
            item["suite"],
            {"total": 0, "passed": 0, "accuracy": 0.0},
        )
        bucket["total"] += 1
        bucket["passed"] += int(item["score"])
    for bucket in by_suite.values():
        bucket["accuracy"] = round(bucket["passed"] / bucket["total"], 4) if bucket["total"] else 0.0
    passed = sum(int(item["score"]) for item in results)
    return {
        "dataset": str(dataset),
        "local_only": True,
        "live_model": False,
        "total": len(results),
        "passed": passed,
        "accuracy": round(passed / len(results), 4) if results else 0.0,
        "ok": passed == len(results),
        "baselines": by_suite,
        "repair_strategy_order": list(REPAIR_STRATEGY_ORDER),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local generate pipeline baseline eval")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_evaluation(args.dataset)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
