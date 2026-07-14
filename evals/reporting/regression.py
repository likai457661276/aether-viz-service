#!/usr/bin/env python3
"""Summarize a local regression and compare it with a local baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _metric_differences(
    baseline: dict[str, Any], current: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_totals = baseline.get("totals", {})
    current_totals = current.get("totals", {})
    common: dict[str, Any] = {}
    for name in sorted(set(baseline_totals) & set(current_totals)):
        before = float(baseline_totals[name]["rate"])
        after = float(current_totals[name]["rate"])
        common[name] = {"baseline": before, "current": after, "delta": round(after - before, 6)}
    live_only = {
        name: current_totals[name]
        for name in sorted(set(current_totals) - set(baseline_totals))
    }
    return common, live_only


def _failure_summary(failures: list[dict[str, Any]]) -> dict[str, Any]:
    metric_counts: Counter[str] = Counter()
    hard_failure_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    dimension_counts: dict[str, Counter[str]] = defaultdict(Counter)
    fallback_topics: Counter[str] = Counter()
    repaired = 0
    for failure in failures:
        if failure.get("kind") == "invalid_case":
            metric_counts["invalid_case"] += 1
            continue
        topic = str(failure.get("topic") or failure.get("id"))
        topic_counts[topic] += 1
        if failure.get("fallback"):
            fallback_topics[topic] += 1
        if failure.get("repaired"):
            repaired += 1
        metric_counts.update(str(name) for name in failure.get("failed_metrics", []))
        for candidate in failure.get("candidate_ranking_report", {}).get("candidates", []):
            hard_failure_counts.update(str(name) for name in candidate.get("hard_failures", []))
        expected = failure.get("diagnostic_alignment", {}).get("expected", {})
        for name, value in expected.items():
            dimension_counts[name][str(value)] += 1
    return {
        "records": len(failures),
        "repaired_records": repaired,
        "metric_counts": dict(metric_counts.most_common()),
        "candidate_hard_failure_counts": dict(hard_failure_counts.most_common()),
        "topic_counts": dict(topic_counts.most_common()),
        "fallback_topic_counts": dict(fallback_topics.most_common()),
        "failed_dimensions": {
            name: dict(values.most_common()) for name, values in sorted(dimension_counts.items())
        },
    }


def _git_metadata(root: Path) -> dict[str, Any]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
        ).stdout
    )
    return {"revision": revision, "dirty": dirty}


def build_report(
    baseline: dict[str, Any],
    current: dict[str, Any],
    failures: list[dict[str, Any]],
    *,
    root: Path,
) -> dict[str, Any]:
    common, live_only = _metric_differences(baseline, current)
    return {
        "local_only": True,
        "git": _git_metadata(root),
        "baseline": {
            "created_at": baseline.get("created_at"),
            "mode": baseline.get("mode"),
            "run_count": baseline.get("run_count"),
            "passed": baseline.get("passed"),
        },
        "current": {
            "created_at": current.get("created_at"),
            "mode": current.get("mode"),
            "run_count": current.get("run_count"),
            "passed": current.get("passed"),
        },
        "version_difference": {
            "common_metric_deltas": common,
            "current_live_only_metrics": live_only,
            "comparison_note": (
                "baseline 为同版本确定性脚手架，current 为真实模型；公共指标可比较，"
                "live-only 指标无历史真实模型基线，不能解释为代码版本升降。"
            ),
        },
        "failures": _failure_summary(failures),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--failures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(
        _load_json(args.baseline),
        _load_json(args.current),
        _load_jsonl(args.failures),
        root=root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
