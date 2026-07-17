"""Deterministic evaluators for generate-pipeline baselines (no live model)."""

from __future__ import annotations

from typing import Any


def route_hit(run: dict[str, Any], example: dict[str, Any]) -> dict[str, object]:
    actual = (run.get("outputs") or {}).get("selected_backend")
    expected = (example.get("outputs") or {}).get("selected_backend")
    return {
        "score": 1 if actual == expected else 0,
        "comment": f"expected={expected!r}, actual={actual!r}",
    }


def hard_validation_pass(run: dict[str, Any], example: dict[str, Any]) -> dict[str, object]:
    actual_ok = bool((run.get("outputs") or {}).get("ok"))
    expected_ok = bool((example.get("outputs") or {}).get("ok"))
    return {
        "score": 1 if actual_ok == expected_ok else 0,
        "comment": f"expected_ok={expected_ok}, actual_ok={actual_ok}",
    }


def repair_success(run: dict[str, Any], example: dict[str, Any]) -> dict[str, object]:
    outputs = run.get("outputs") or {}
    expected = example.get("outputs") or {}
    actual = bool(outputs.get("repaired_ok"))
    want = bool(expected.get("repaired_ok"))
    return {
        "score": 1 if actual == want else 0,
        "comment": (
            f"expected_repaired_ok={want}, actual_repaired_ok={actual}, "
            f"strategy={outputs.get('strategy')!r}"
        ),
    }
