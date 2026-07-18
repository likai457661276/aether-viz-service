"""Single-metric deterministic evaluator for number-line IR regression."""

from __future__ import annotations


def number_line_ir_match(run, example) -> dict[str, object]:
    actual = run.outputs if hasattr(run, "outputs") else run.get("outputs", {}) or {}
    expected = example.outputs if hasattr(example, "outputs") else example.get("outputs", {}) or {}
    checks = {key: actual.get(key) == value for key, value in expected.items() if key != "before_error"}
    if "before_error" in expected:
        checks["before_error"] = expected["before_error"] in actual.get("before_error_types", [])
    if "runtime_errors" in actual:
        checks["runtime_errors_empty"] = not actual["runtime_errors"]
    if "after_error_types" in actual:
        checks["after_errors_empty"] = not actual["after_error_types"]
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "score": 0 if failed else 1,
        "comment": "passed" if not failed else f"failed={','.join(failed)}",
    }
