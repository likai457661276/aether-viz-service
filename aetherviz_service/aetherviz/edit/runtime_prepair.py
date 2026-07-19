"""Deterministic runtime pre-repair for proven DOM API contract errors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aetherviz_service.aetherviz.contracts.validation.dom_api_contract import (
    find_dom_element_selector_mismatches,
    repair_dom_element_selector_mismatches,
)


@dataclass(frozen=True)
class RuntimePreRepairResult:
    html: str
    applied: tuple[str, ...]
    guard: Callable[[str], list[str]]


def try_deterministic_runtime_prepair(
    business_html: str,
    runtime_error: dict[str, Any] | None,
) -> RuntimePreRepairResult | None:
    """Repair DOM-as-selector misuse when the runtime error matches the known pattern."""
    error_text = " ".join(str(value) for value in (runtime_error or {}).values()).lower()
    if not ("queryselector" in error_text and "not a valid selector" in error_text and "[object html" in error_text):
        return None
    repaired, applied = repair_dom_element_selector_mismatches(business_html)
    if not applied or repaired == business_html:
        return None

    def guard(candidate: str) -> list[str]:
        return (
            ["edit_runtime_error_still_present:dom_element_used_as_selector"]
            if find_dom_element_selector_mismatches(candidate)
            else []
        )

    return RuntimePreRepairResult(
        html=repaired,
        applied=tuple(f"function:{name}" for name in applied),
        guard=guard,
    )


def combine_candidate_guards(
    *guards: Callable[[str], list[str]] | None,
) -> Callable[[str], list[str]] | None:
    active = [guard for guard in guards if guard is not None]
    if not active:
        return None
    if len(active) == 1:
        return active[0]

    def combined(candidate: str) -> list[str]:
        errors: list[str] = []
        for guard in active:
            errors.extend(guard(candidate))
        return errors

    return combined
