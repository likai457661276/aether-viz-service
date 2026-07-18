"""Run the repository-local IR routing regression set without remote datasets."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings
from evals.evaluators.ir_routing import route_exact_match, route_is_registered_or_direct

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "ir_routing"


@dataclass(frozen=True)
class LocalRecord:
    outputs: dict[str, Any]


def run_route(inputs: dict[str, Any]) -> dict[str, Any]:
    topic = str(inputs.get("topic") or "")
    plan_seed = inputs.get("plan") if isinstance(inputs.get("plan"), dict) else {}
    return resolve_generation_route(normalize_plan(plan_seed, topic)).as_dict()


def evaluate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for row in rows:
        output = run_route(row["inputs"])
        run = LocalRecord(output)
        example = LocalRecord(row["outputs"])
        exact = route_exact_match(run, example)
        valid = route_is_registered_or_direct(run, example)
        results.append(
            {
                "topic": row["inputs"]["topic"],
                "expected": row["outputs"]["selected_backend"],
                "actual": output["selected_backend"],
                "route_source": output["source"],
                "llm_invoked": output["llm_invoked"],
                "exact_match": exact["score"],
                "valid_selection": valid["score"],
                "comment": exact["comment"],
                "tags": row.get("tags", []),
            }
        )
    registered = {backend.key for backend in DEFAULT_IR_REGISTRY.backends()}
    covered = {str(item["expected"]) for item in results if item["expected"] is not None}
    missing = sorted(registered - covered)
    passed = sum(int(item["exact_match"]) for item in results)
    return {
        "total": len(results),
        "passed": passed,
        "accuracy": round(passed / len(results), 4) if results else 0,
        "backend_coverage": {
            "registered": sorted(registered),
            "covered": sorted(registered & covered),
            "missing": missing,
            "ok": not missing,
        },
        "ok": passed == len(results) and not missing,
        "results": results,
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    return [
        json.loads(line)
        for file in files
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--enable-llm", action="store_true")
    args = parser.parse_args()
    settings.aetherviz_ir_router_enabled = bool(args.enable_llm)
    rows = load_rows(args.dataset)
    report = {
        "dataset": str(args.dataset),
        "llm_enabled": bool(args.enable_llm),
        **evaluate_rows(rows),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
