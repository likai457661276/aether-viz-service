"""Deterministic evaluators for bounded Geometry IR completion strategies."""

from __future__ import annotations

import math
from typing import Any


def evaluate_completion_case(result: dict[str, Any], example: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one controlled completion run against its expected strategy contract."""
    expected = example.get("outputs", {})
    initial_failures = set(result.get("initial_hard_failures", []))
    expected_failures = set(expected.get("expected_initial_hard_failures", []))
    attempts = [
        item
        for item in result.get("completion_reports", [])
        if isinstance(item, dict) and item.get("attempted")
    ]
    successes = sum(bool(item.get("ok")) for item in attempts)
    success_rate = successes / len(attempts) if attempts else 0.0
    minimum_attempts = int(expected.get("minimum_attempts", 1))
    required_success_rate = float(expected.get("required_success_rate", 1.0))
    checks = {
        "initial_failure_match": initial_failures == expected_failures,
        "strategy_match": result.get("strategy") == expected.get("expected_strategy"),
        "minimum_attempts": len(attempts) >= minimum_attempts,
        "completion_success_rate": success_rate >= required_success_rate,
        "final_ranking": bool(result.get("final_ranking_ok")),
        "final_assembly": bool(result.get("final_assembly_ok")),
        "scene_contract": bool(result.get("scene_report", {}).get("ok")),
        "assembly_metrics_preserved": _assembly_metrics_preserved(result, expected),
    }
    return {
        "ok": all(checks.values()),
        "case_id": example.get("id"),
        "checks": checks,
        "attempts": len(attempts),
        "successes": successes,
        "success_rate": round(success_rate, 6),
        "initial_hard_failures": sorted(initial_failures),
        "strategy": result.get("strategy"),
    }


def _assembly_metrics_preserved(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    metrics = expected.get("preserved_assembly_metrics", [])
    before_states = result.get("assembly_before", {}).get("states", [])
    after_states = result.get("assembly_after", {}).get("states", [])
    if not isinstance(metrics, list) or not metrics:
        return True
    if not isinstance(before_states, list) or len(before_states) != len(after_states):
        return False
    for before, after in zip(before_states, after_states, strict=True):
        if not isinstance(before, dict) or not isinstance(after, dict):
            return False
        for metric in metrics:
            left = before.get(metric)
            right = after.get(metric)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                if not math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9):
                    return False
            elif left != right:
                return False
    return True
