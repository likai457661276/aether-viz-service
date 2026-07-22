#!/usr/bin/env python3
"""Classify recomposition eval failures into stable stage-owned clusters."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


FAILURE_CLASSES = (
    ("F1_plan_infeasible", ("expanded_piece_budget", "unsupported_", "stage_count")),
    ("F2_construction_unsolved", ("unmaterialized_target_construction", "construction_")),
    ("F3_schema_or_parse", ("geometry_ir_parse", "schema:", "geometry_ir_normalization")),
    ("F4_teaching_waypoint", ("teaching:missing_intermediate_geometry_stage",)),
    ("F5_assembly_bounds", ("assembly:target_assembly_out_of_bounds",)),
    ("F6_footprint_scale", ("safety:undersized_visual_footprint", "undersized_visual_footprint", "visual_scale_range_conflict")),
    (
        "F7_assembly_or_math_hard",
        (
            "assembly:target_assembly_failed",
            "mathematical_",
            "target_assembly_failed",
            "mathematical_invariant",
        ),
    ),
    ("F8_repair_exhausted", ("initial=", "repair=", "ir_generation_failed", "fallback")),
)


def classify_signal(signal: str) -> str:
    text = str(signal or "")
    for class_name, needles in FAILURE_CLASSES:
        if any(needle in text for needle in needles):
            return class_name
    return "F9_other"


def _signals_from_record(record: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    kind = str(record.get("kind") or "run")
    if kind == "feasibility_case":
        signals.extend(str(item) for item in record.get("error_types", []))
        return signals or ["feasibility_case"]
    if kind == "completion_case":
        signals.extend(str(item) for item in record.get("initial_hard_failures", []))
        signals.extend(str(item) for item in record.get("final_hard_failures", []))
        if record.get("strategy"):
            signals.append(f"strategy:{record['strategy']}")
        return signals or ["completion_case"]
    if kind == "invalid_case":
        return ["invalid_case"]
    signals.extend(str(name) for name in record.get("failed_metrics", []))
    ranking = record.get("candidate_ranking_report") or {}
    for candidate in ranking.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        signals.extend(str(name) for name in candidate.get("hard_failures", []))
    feasibility = record.get("plan_feasibility") or {}
    signals.extend(str(name) for name in feasibility.get("error_types", []))
    if record.get("fallback"):
        signals.append("fallback")
    if record.get("repair_attempted") and not record.get("repaired"):
        signals.append("repair_exhausted")
    if record.get("generation_error"):
        signals.append(str(record["generation_error"]))
    if record.get("repair_error"):
        signals.append(str(record["repair_error"]))
    return signals


def classify_record(record: dict[str, Any]) -> dict[str, Any]:
    signals = _signals_from_record(record)
    class_counts: Counter[str] = Counter(classify_signal(signal) for signal in signals)
    ranked = [
        name
        for name, _ in sorted(
            ((name, class_counts[name]) for name in dict(FAILURE_CLASSES)),
            key=lambda item: (-item[1], item[0]),
        )
        if class_counts[name] > 0
    ]
    if class_counts.get("F9_other") and not ranked:
        ranked = ["F9_other"]
    primary = ranked[0] if ranked else "F9_other"
    return {
        "id": record.get("id") or record.get("case_id") or record.get("topic"),
        "kind": record.get("kind") or "run",
        "topic": record.get("topic"),
        "primary_class": primary,
        "class_counts": dict(class_counts),
        "signals": signals,
        "failed_metrics": record.get("failed_metrics", []),
        "strategy": (record.get("candidate_ranking_report") or {}).get("strategy")
        or record.get("strategy"),
        "repaired": bool(record.get("repaired")),
        "fallback": bool(record.get("fallback")),
    }


def build_failure_classification_report(
    failures: list[dict[str, Any]],
    *,
    runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    classified = [classify_record(item) for item in failures]
    cluster_counts = Counter(item["primary_class"] for item in classified)
    signal_counts: Counter[str] = Counter()
    for item in classified:
        signal_counts.update(item["signals"])

    near_misses: list[dict[str, Any]] = []
    if runs:
        for run in runs:
            ranking = run.get("candidate_ranking_report") or {}
            hard_failures = [
                str(name)
                for candidate in ranking.get("candidates", [])
                if isinstance(candidate, dict)
                for name in candidate.get("hard_failures", [])
            ]
            history = ranking.get("completion_history") or []
            rescued = bool(ranking.get("ok")) and any(
                isinstance(item, dict) and int(item.get("accepted") or 0) > 0 for item in history
            )
            if hard_failures or rescued or run.get("repaired") or run.get("fallback"):
                near_misses.append(
                    {
                        "id": run.get("id"),
                        "topic": run.get("topic"),
                        "strategy": ranking.get("strategy"),
                        "hard_failures": hard_failures,
                        "completion_history": history,
                        "repaired": bool(run.get("repaired")),
                        "fallback": bool(run.get("fallback")),
                        "primary_class": classify_signal(hard_failures[0]) if hard_failures else (
                            "F8_repair_exhausted"
                            if run.get("fallback") or run.get("repair_attempted")
                            else "rescued_by_deterministic_completion"
                        ),
                    }
                )

    near_miss_counts = Counter(item["primary_class"] for item in near_misses)
    largest = cluster_counts.most_common(1)
    largest_near = near_miss_counts.most_common(1)
    return {
        "local_only": True,
        "failure_records": len(failures),
        "classified_failures": classified,
        "cluster_counts": dict(cluster_counts.most_common()),
        "signal_counts": dict(signal_counts.most_common()),
        "largest_remaining_cluster": (
            {"class": largest[0][0], "count": largest[0][1]} if largest else None
        ),
        "near_miss_records": len(near_misses),
        "near_miss_cluster_counts": dict(near_miss_counts.most_common()),
        "largest_near_miss_cluster": (
            {"class": largest_near[0][0], "count": largest_near[0][1]} if largest_near else None
        ),
        "near_misses": near_misses,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failures", type=Path, required=True)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_failure_classification_report(
        _load_jsonl(args.failures),
        runs=_load_jsonl(args.runs) if args.runs else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "largest_remaining_cluster": report["largest_remaining_cluster"],
                "largest_near_miss_cluster": report["largest_near_miss_cluster"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
