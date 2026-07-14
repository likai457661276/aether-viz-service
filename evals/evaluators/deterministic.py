"""Deterministic local evaluators for recomposition regression outputs."""

from __future__ import annotations

from collections import Counter
from typing import Any

from aetherviz_service.aetherviz.constants import MODEL_HTML_HARD_LIMIT_CHARS

REQUIRED_DIMENSIONS: dict[str, set[object]] = {
    "piece_count": {"1", "2", "3", "4+"},
    "primary_transform": {"translation", "rotation", "reflection", "combined"},
    "math_relation": {"area", "length", "angle", "congruence"},
    "representation": {"polygon", "segment", "angle", "grid"},
    "stage_count": {3, 4, 5},
    "derivation_difficulty": {"single_step", "two_step", "multi_step"},
    "parameter_form": {"fixed", "variable", "boundary"},
    "failure_mode": {"missing_stage", "wrong_relation", "text_conflict", "out_of_bounds"},
}


def validate_dataset_matrix(examples: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate local schema and prove that every requested dimension is covered."""
    errors: list[dict[str, Any]] = []
    coverage: dict[str, dict[str, int]] = {}
    ids: set[str] = set()
    if not 24 <= len(examples) <= 30:
        errors.append({"type": "dataset_size", "expected": [24, 30], "actual": len(examples)})
    for index, example in enumerate(examples):
        example_id = str(example.get("id") or "")
        if not example_id or example_id in ids:
            errors.append({"type": "dataset_id", "index": index, "id": example_id})
        ids.add(example_id)
        if not isinstance(example.get("inputs"), dict) or not str(example["inputs"].get("topic") or ""):
            errors.append({"type": "dataset_inputs", "index": index})
        if not isinstance(example.get("outputs"), dict):
            errors.append({"type": "dataset_outputs", "index": index})
        dimensions = example.get("metadata", {}).get("dimensions", {})
        if not isinstance(dimensions, dict):
            errors.append({"type": "dataset_dimensions", "index": index})
            continue
        for name in REQUIRED_DIMENSIONS:
            if name not in dimensions:
                errors.append({"type": "missing_dimension", "index": index, "dimension": name})
    for name, required in REQUIRED_DIMENSIONS.items():
        counts = Counter(
            example.get("metadata", {}).get("dimensions", {}).get(name) for example in examples
        )
        coverage[name] = {str(value): counts[value] for value in sorted(required, key=str)}
        missing = sorted(required - set(counts), key=str)
        if missing:
            errors.append({"type": "matrix_coverage", "dimension": name, "missing": missing})
    return {"ok": not errors, "example_count": len(examples), "coverage": coverage, "errors": errors}


def evaluate_run(
    result: dict[str, Any],
    example: dict[str, Any],
    *,
    live_model: bool,
    browser_enabled: bool,
) -> dict[str, bool]:
    """Return objective local metrics; skipped capabilities are not reported as passes."""
    scores = {
        "profile_match": result.get("profile", {}).get("representation_type")
        == example.get("outputs", {}).get("expected_profile"),
        "scene_contract": bool(result.get("scene_report", {}).get("ok")),
        "html_hard_validation": bool(result.get("html_report", {}).get("ok")),
        "mathematical_invariants": _mathematical_checks_pass(result),
        "teaching_semantics": bool(result.get("semantic_report", {}).get("ok")),
        "stage_count_match": _stage_count_matches(result, example),
    }
    if browser_enabled:
        scores["browser_runtime"] = bool(result.get("browser_report", {}).get("ok"))
    if live_model:
        scores.update(
            {
                "initial_geometry_ir_contract": bool(
                    result.get("initial_geometry_ir_report", {}).get("ok")
                ),
                "candidate_ranking": _candidate_ranking_pass(result),
                "no_generic_fallback": not bool(result.get("fallback")),
            }
        )
    return scores


def html_hard_validation_pass(result: dict[str, Any], _example: dict[str, Any]) -> bool:
    """Validate the HTML report and enforce the shared production hard limit."""
    return bool(result["html_report"].get("ok")) and result["business_chars"] <= MODEL_HTML_HARD_LIMIT_CHARS


def diagnostic_alignment(result: dict[str, Any], example: dict[str, Any]) -> dict[str, Any]:
    """Report intended-vs-generated facts without turning heuristic intent into a hard gate."""
    expected = example.get("outputs", {}).get("expected_constraints", {})
    facts = result.get("geometry_ir_facts", {})
    counts = facts.get("piece_counts", [])
    return {
        "piece_count": _piece_bucket_matches(counts, str(expected.get("piece_count") or "")),
        "primary_transform": _transform_matches(
            set(facts.get("transforms", [])), str(expected.get("primary_transform") or "")
        ),
        "stage_count": facts.get("stage_count") == expected.get("stage_count"),
        "generated": facts,
        "expected": expected,
    }


def _mathematical_checks_pass(result: dict[str, Any]) -> bool:
    report = result.get("semantic_report", {})
    checks = [item for item in report.get("checks", []) if item.get("kind") in {"invariant", "relation"}]
    return bool(checks) and all(item.get("passed") is not False for item in checks)


def _stage_count_matches(result: dict[str, Any], example: dict[str, Any]) -> bool:
    expected = example.get("outputs", {}).get("expected_constraints", {}).get("stage_count")
    return result.get("geometry_ir_facts", {}).get("stage_count") == expected


def _candidate_ranking_pass(result: dict[str, Any]) -> bool:
    report = result.get("candidate_ranking_report", {})
    ranking = report.get("ranking")
    return bool(report.get("ok")) and isinstance(ranking, list) and bool(ranking)


def _piece_bucket_matches(counts: object, bucket: str) -> bool:
    if not isinstance(counts, list) or not counts:
        return False
    if bucket == "4+":
        return all(isinstance(value, int) and value >= 4 for value in counts)
    return bucket.isdigit() and all(value == int(bucket) for value in counts)


def _transform_matches(actual: set[str], expected: str) -> bool:
    if expected == "combined":
        return len(actual & {"translation", "rotation", "reflection"}) >= 2
    return expected in actual
