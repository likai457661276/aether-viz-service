"""Run the local IR stability failure-mode regression set.

Organized by interactive_type × representation_type × failure_mode.
Deterministic by default; does not call models or upload LangSmith datasets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.datasets.ir_stability.taxonomy import matrix_key, required_coverage
from evals.evaluators.ir_stability import ir_stability_match
from evals.targets.ir_stability import run_ir_stability_case

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "ir_stability" / "failure_modes.jsonl"


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def coverage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed = {matrix_key(row) for row in rows}
    required = required_coverage()
    missing = [list(item) for item in required if item not in observed]
    return {
        "required": [list(item) for item in required],
        "observed": [list(item) for item in sorted(observed)],
        "missing": missing,
        "ok": not missing,
    }


def evaluate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for row in rows:
        output = run_ir_stability_case(row["inputs"])
        evaluation = ir_stability_match(output, row["outputs"])
        interactive, representation, failure_mode = matrix_key(row)
        results.append(
            {
                "case_id": row["inputs"]["case_id"],
                "interactive_type": interactive,
                "representation_type": representation,
                "failure_mode": failure_mode,
                "score": evaluation["score"],
                "comment": evaluation["comment"],
                **output,
            }
        )
    passed = sum(int(item["score"]) for item in results)
    coverage = coverage_report(rows)
    return {
        "total": len(results),
        "passed": passed,
        "ok": passed == len(results) and coverage["ok"],
        "coverage": coverage,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = load_rows(args.dataset)
    report = {"dataset": str(args.dataset), **evaluate_rows(rows)}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
