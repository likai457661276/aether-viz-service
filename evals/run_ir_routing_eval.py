"""Run the repository-local IR routing regression set without remote datasets."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings
from evals.evaluators.ir_routing import route_exact_match, route_is_registered_or_direct

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "ir_routing" / "routing_core.jsonl"


@dataclass(frozen=True)
class LocalRecord:
    outputs: dict[str, Any]


def run_route(inputs: dict[str, Any]) -> dict[str, Any]:
    topic = str(inputs.get("topic") or "")
    return resolve_generation_route(normalize_plan({}, topic)).as_dict()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--enable-llm", action="store_true")
    args = parser.parse_args()
    settings.aetherviz_ir_router_enabled = bool(args.enable_llm)
    rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
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
    passed = sum(int(item["exact_match"]) for item in results)
    report = {
        "dataset": str(args.dataset),
        "total": len(results),
        "passed": passed,
        "accuracy": round(passed / len(results), 4) if results else 0,
        "llm_enabled": bool(args.enable_llm),
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
