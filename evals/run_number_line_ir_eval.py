"""Run the repository-local number-line IR and Runtime regression set."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.evaluators.number_line_ir import number_line_ir_match
from evals.targets.number_line_ir import run_number_line_ir_case

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "number_line_ir" / "regression.jsonl"


@dataclass(frozen=True)
class LocalRecord:
    outputs: dict[str, Any]


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for row in rows:
        output = run_number_line_ir_case(row["inputs"])
        evaluation = number_line_ir_match(LocalRecord(output), LocalRecord(row["outputs"]))
        results.append(
            {
                "case_id": row["inputs"]["case_id"],
                "score": evaluation["score"],
                "comment": evaluation["comment"],
                **output,
            }
        )
    passed = sum(int(item["score"]) for item in results)
    return {"total": len(results), "passed": passed, "ok": passed == len(results), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"dataset": str(args.dataset), **evaluate_rows(load_rows(args.dataset))}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
