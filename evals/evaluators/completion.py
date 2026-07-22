"""Deterministic evaluators for bounded Geometry IR completion strategies."""

from __future__ import annotations

import math
from typing import Any


def evaluate_completion_case(result: dict[str, Any], example: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one controlled completion/construction run against its contract."""
    expected = example.get("outputs", {})
    pipeline = str(result.get("pipeline") or example.get("inputs", {}).get("pipeline") or "composite")
    if pipeline == "construction":
        return _evaluate_construction_case(result, example)

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
    expected_ranking_ok = bool(expected.get("expected_final_ranking_ok", True))
    expected_assembly_ok = bool(expected.get("expected_final_assembly_ok", True))
    expected_scene_ok = bool(expected.get("expected_scene_contract_ok", True))
    checks = {
        "initial_failure_match": initial_failures == expected_failures,
        "strategy_match": result.get("strategy") == expected.get("expected_strategy"),
        "minimum_attempts": len(attempts) >= minimum_attempts,
        "completion_success_rate": success_rate >= required_success_rate,
        "final_ranking": bool(result.get("final_ranking_ok")) == expected_ranking_ok,
        "final_assembly": bool(result.get("final_assembly_ok")) == expected_assembly_ok,
        "scene_contract": bool(result.get("scene_report", {}).get("ok")) == expected_scene_ok,
        "assembly_metrics_preserved": _assembly_metrics_preserved(result, expected),
        "remaining_hard_failures": _optional_set_match(
            result.get("final_hard_failures", []),
            expected.get("expected_remaining_hard_failures"),
        ),
        "removed_hard_failures": _removed_hard_failures_match(result, expected),
    }
    return {
        "ok": all(checks.values()),
        "case_id": example.get("id"),
        "pipeline": pipeline,
        "checks": checks,
        "attempts": len(attempts),
        "successes": successes,
        "success_rate": round(success_rate, 6),
        "initial_hard_failures": sorted(initial_failures),
        "final_hard_failures": sorted(str(item) for item in result.get("final_hard_failures", [])),
        "strategy": result.get("strategy"),
    }


def evaluate_feasibility_case(result: dict[str, Any], example: dict[str, Any]) -> dict[str, Any]:
    expected = example.get("outputs", {})
    expected_types = set(expected.get("expected_error_types", []))
    actual_types = set(result.get("error_types", []))
    checks = {
        "ok_match": bool(result.get("ok")) == bool(expected.get("expected_ok", False)),
        "error_types": actual_types == expected_types,
        "route_eligible": bool(result.get("route_eligible"))
        == bool(expected.get("expected_route_eligible", False)),
    }
    return {
        "ok": all(checks.values()),
        "case_id": example.get("id"),
        "pipeline": "feasibility",
        "checks": checks,
        "error_types": sorted(actual_types),
        "route_eligible": bool(result.get("route_eligible")),
    }


def _evaluate_construction_case(result: dict[str, Any], example: dict[str, Any]) -> dict[str, Any]:
    expected = example.get("outputs", {})
    checks = {
        "construction_ok": bool(result.get("construction_ok"))
        == bool(expected.get("expected_construction_ok", True)),
        "construction_changed": bool(result.get("construction_changed"))
        == bool(expected.get("expected_construction_changed", True)),
        "unmaterialized_rejected": bool(result.get("unmaterialized_rejected"))
        == bool(expected.get("expected_unmaterialized_rejected", True)),
        "final_ranking": bool(result.get("final_ranking_ok"))
        == bool(expected.get("expected_final_ranking_ok", True)),
        "final_assembly": bool(result.get("final_assembly_ok"))
        == bool(expected.get("expected_final_assembly_ok", True)),
        "scene_contract": bool(result.get("scene_report", {}).get("ok")),
    }
    return {
        "ok": all(checks.values()),
        "case_id": example.get("id"),
        "pipeline": "construction",
        "checks": checks,
        "attempts": 1 if result.get("construction_changed") else 0,
        "successes": 1 if result.get("construction_ok") else 0,
        "success_rate": 1.0 if result.get("construction_ok") else 0.0,
        "initial_hard_failures": [],
        "final_hard_failures": sorted(str(item) for item in result.get("final_hard_failures", [])),
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


def _optional_set_match(actual: object, expected: object) -> bool:
    if expected is None:
        return True
    return set(str(item) for item in (actual or [])) == set(str(item) for item in expected)


def _removed_hard_failures_match(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    expected_removed = expected.get("expected_removed_hard_failures")
    if expected_removed is None:
        return True
    removed: set[str] = set()
    for report in result.get("completion_reports", []):
        if not isinstance(report, dict) or not report.get("accepted"):
            continue
        removed.update(str(item) for item in report.get("removed_hard_failures", []))
    return removed == set(str(item) for item in expected_removed)
