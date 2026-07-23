"""Shared IR stability failure-mode taxonomy for offline regression.

Dimensions follow AGENTS.md: interactive_type × representation_type × failure_mode.
Cases must cover reusable teaching patterns, never single-knowledge-point templates.
"""

from __future__ import annotations

from typing import Any

# Stable failure-mode ids used in datasets and reporting.
FAILURE_MODES: tuple[str, ...] = (
    "stream_incomplete_json",
    "schema_or_parse",
    "hard_validation",
    "multi_candidate_selection",
    "repair_exhausted_signal",
)

# Backends prioritized by the IR→HTML stability workstream.
STABILITY_BACKENDS: tuple[str, ...] = (
    "recomposition_scene",
    "coordinate_graph_scene",
    "linked_coordinate_scene",
    "data_distribution_scene",
    "constraint_geometry_scene",
)


def classify_failure_mode(signals: list[str]) -> str:
    joined = " | ".join(str(item) for item in signals)
    lower = joined.lower()
    if any(token in lower for token in ("incomplete_json", "ir_stream_", "jsondecode", "truncated")):
        return "stream_incomplete_json"
    if any(token in lower for token in ("schema:", "parse", "normalization", "trailing_content")):
        return "schema_or_parse"
    if any(token in lower for token in ("repair_exhausted", "ir_generation_failed", "repair=")):
        return "repair_exhausted_signal"
    if any(token in lower for token in ("selected_index", "multi_candidate", "ranking_ok")):
        return "multi_candidate_selection"
    if any(
        token in lower
        for token in (
            "hard_failure",
            "invariant",
            "assembly:",
            "teaching:",
            "safety:",
            "invalid_",
            "geometry_invariant",
        )
    ):
        return "hard_validation"
    return "hard_validation"


def matrix_key(row: dict[str, Any]) -> tuple[str, str, str]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    plan = row.get("inputs", {}).get("plan") if isinstance(row.get("inputs"), dict) else {}
    plan = plan if isinstance(plan, dict) else {}
    profile = plan.get("knowledge_profile") if isinstance(plan.get("knowledge_profile"), dict) else {}
    interactive = str(
        metadata.get("interactive_type")
        or plan.get("interactive_type")
        or "unknown"
    )
    representation = str(
        metadata.get("representation_type")
        or profile.get("representation_type")
        or "unknown"
    )
    failure_mode = str(metadata.get("failure_mode") or "unknown")
    return interactive, representation, failure_mode


def required_coverage() -> list[tuple[str, str, str]]:
    """Minimum offline coverage gates for the stability dataset."""
    return [
        ("simulation", "linked_coordinate_scene", "hard_validation"),
        ("simulation", "linked_coordinate_scene", "multi_candidate_selection"),
        ("simulation", "coordinate_graph", "hard_validation"),
        ("simulation", "data_chart", "schema_or_parse"),
        ("simulation", "geometric_recomposition", "hard_validation"),
        ("simulation", "geometric_construction", "hard_validation"),
        ("simulation", "coordinate_graph", "stream_incomplete_json"),
    ]
