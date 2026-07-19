"""Single-metric deterministic evaluator for constraint-geometry IR regression."""

from __future__ import annotations


def constraint_geometry_ir_match(run, example) -> dict[str, object]:
    actual = run.outputs if hasattr(run, "outputs") else run.get("outputs", {}) or {}
    expected = example.outputs if hasattr(example, "outputs") else example.get("outputs", {}) or {}
    checks: dict[str, bool] = {}
    for key, value in expected.items():
        if key == "before_error":
            checks[key] = value in actual.get("before_error_types", [])
        elif key in {"kept_constraint_types", "dropped_constraint_types"}:
            checks[key] = sorted(actual.get(key) or []) == sorted(value or [])
        else:
            checks[key] = actual.get(key) == value
    if "after_error_types" in actual:
        checks["after_errors_empty"] = not actual["after_error_types"]
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "score": 0 if failed else 1,
        "comment": "passed" if not failed else f"failed={','.join(failed)}",
    }
