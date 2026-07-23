"""Shared IR multi-candidate envelope helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# High-frequency backends ask for 3 candidates in one call (min 2 accepted).
IR_CANDIDATE_MIN_ITEMS = 2
IR_CANDIDATE_MAX_ITEMS = 3


def candidates_envelope_schema(
    item_schema: dict[str, Any],
    *,
    min_items: int = IR_CANDIDATE_MIN_ITEMS,
    max_items: int = IR_CANDIDATE_MAX_ITEMS,
) -> dict[str, Any]:
    """Wrap a single-IR JSON Schema as a ranked multi-candidate envelope."""
    candidate = deepcopy(item_schema)
    definitions = candidate.pop("$defs", None)
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {
            "candidates": {
                "type": "array",
                "items": candidate,
                "minItems": min_items,
                "maxItems": max_items,
            }
        },
    }
    if definitions is not None:
        schema["$defs"] = definitions
    return schema


def validate_candidate_count(
    candidates: object,
    *,
    min_items: int = IR_CANDIDATE_MIN_ITEMS,
    max_items: int = IR_CANDIDATE_MAX_ITEMS,
) -> list[Any]:
    if not isinstance(candidates, list) or not min_items <= len(candidates) <= max_items:
        raise ValueError(f"ir_candidates_must_contain_{min_items}_to_{max_items}_items")
    return candidates
