"""Evaluators for IR stability failure-mode regression rows."""

from __future__ import annotations

from typing import Any


def ir_stability_match(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    for key, value in expected.items():
        if actual.get(key) != value:
            failures.append(f"{key}:{actual.get(key)!r}!={value!r}")
    return {
        "score": 0.0 if failures else 1.0,
        "comment": ",".join(failures) if failures else "ok",
        "failures": failures,
    }
