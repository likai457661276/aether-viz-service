"""Local deterministic evaluators for plan-aware IR routing."""

from __future__ import annotations


def route_exact_match(run, example) -> dict[str, object]:
    run_outputs = run.outputs if hasattr(run, "outputs") else run.get("outputs", {}) or {}
    example_outputs = example.outputs if hasattr(example, "outputs") else example.get("outputs", {}) or {}
    actual = run_outputs.get("selected_backend")
    expected = example_outputs.get("selected_backend")
    return {
        "score": 1 if actual == expected else 0,
        "comment": f"expected={expected!r}, actual={actual!r}",
    }


def route_is_registered_or_direct(run, _example) -> dict[str, object]:
    from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY

    run_outputs = run.outputs if hasattr(run, "outputs") else run.get("outputs", {}) or {}
    actual = run_outputs.get("selected_backend")
    allowed = {None, *(backend.key for backend in DEFAULT_IR_REGISTRY.backends())}
    return {
        "score": 1 if actual in allowed else 0,
        "comment": f"selected_backend={actual!r}",
    }
