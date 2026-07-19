"""Deterministic edit execution strategy routing."""

from __future__ import annotations

from typing import Any, Literal

from aetherviz_service.aetherviz.edit.spec import EditOperation, operations_are_deterministic
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

EditExecutionStrategy = Literal[
    "deterministic_patch",
    "scoped_model_patch",
    "full_html_regeneration",
]

_CROSS_LAYER_AREAS = frozenset({"state", "render", "events", "animation", "runtime"})
_STRUCTURAL_AREAS = frozenset({"dom", "svg_canvas", "shell_content"})
_SCOPED_MAX_SCORE = 6


def complexity_score(
    *,
    targets: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    impact_areas: tuple[str, ...] | list[str],
    operations: tuple[EditOperation, ...] | list[EditOperation] = (),
) -> int:
    """Score edit complexity for strategy routing.

    Formula (from upgrade plan):
      target_count * 1
      + impact_area_count * 2
      + cross_layer_dependency_count * 3
      + structural_change * 5
    """

    target_count = len(targets)
    impact = tuple(impact_areas)
    impact_area_count = len(impact)
    cross_layer = len([area for area in impact if area in _CROSS_LAYER_AREAS])
    structural = 1 if any(area in _STRUCTURAL_AREAS for area in impact) else 0
    # remove_element is structural even without impact_areas hint
    if any(op.type == "remove_element" for op in operations):
        structural = 1
    return target_count * 1 + impact_area_count * 2 + cross_layer * 3 + structural * 5


def route_edit_strategy(
    *,
    diagnosis: Any,
    business_html: str,
) -> tuple[EditExecutionStrategy, dict[str, Any]]:
    """Choose the cheapest safe execution strategy for a normalized diagnosis."""

    if getattr(diagnosis, "strategy", None) == "clarification_required":
        return "full_html_regeneration", {
            "reason": "clarification_required",
            "complexity_score": 0,
            "operations_bindable": False,
            "operations_cover_requirements": False,
            "scoped_targets_bindable": False,
        }

    operations: tuple[EditOperation, ...] = tuple(getattr(diagnosis, "operations", ()) or ())
    targets = tuple(getattr(diagnosis, "targets", ()) or ())
    impact_areas = tuple(getattr(diagnosis, "impact_areas", ()) or ())
    score = complexity_score(targets=targets, impact_areas=impact_areas, operations=operations)
    ops_ok = operations_are_deterministic(operations)
    ops_cover_requirements = _operations_cover_requirements(diagnosis, operations)
    scoped_ok = _scoped_targets_bindable(targets, business_html)

    # Bindable deterministic ops are always preferred; intent hard-check failures
    # upgrade the ladder to scoped / full regeneration.
    if ops_ok and ops_cover_requirements:
        strategy: EditExecutionStrategy = "deterministic_patch"
        reason = "operations_bindable"
    elif scoped_ok and score <= _SCOPED_MAX_SCORE:
        strategy = "scoped_model_patch"
        reason = "scoped_targets_medium_complexity"
    else:
        strategy = "full_html_regeneration"
        reason = "operations_incomplete" if ops_ok and not ops_cover_requirements else "high_complexity_or_unbound"

    return strategy, {
        "reason": reason,
        "complexity_score": score,
        "operations_bindable": ops_ok,
        "operations_cover_requirements": ops_cover_requirements,
        "scoped_targets_bindable": scoped_ok,
        "operation_count": len(operations),
        "target_count": len(targets),
        "impact_areas": list(impact_areas),
    }


def _operations_cover_requirements(diagnosis: Any, operations: tuple[EditOperation, ...]) -> bool:
    """Conservatively require deterministic operations to cover every hard change claim."""

    if not operations or tuple(getattr(diagnosis, "dropped_operations", ()) or ()):
        return False
    hard_checks = tuple(
        check
        for check in tuple(getattr(diagnosis, "change_checks", ()) or ())
        if getattr(check, "severity", "hard") == "hard"
    )
    specific_checks = tuple(check for check in hard_checks if check.kind != "html_must_differ")
    if specific_checks:
        checks_covered = all(
            any(_operation_covers_check(operation, check) for operation in operations) for check in specific_checks
        )
        operations_verified = all(
            any(_operation_covers_check(operation, check) for check in specific_checks) for operation in operations
        )
        return checks_covered and operations_verified

    # A generic document-diff check cannot prove that multiple independent requirements
    # were implemented. Escalate instead of accepting the first observable change.
    requirements = tuple(getattr(diagnosis, "change_requirements", ()) or ())
    return len(requirements) <= 1 and len(operations) == 1


def _operation_covers_check(operation: EditOperation, check: Any) -> bool:
    kind = str(getattr(check, "kind", "") or "")
    selector = str(getattr(check, "selector", "") or "")
    property_name = str(getattr(check, "property", "") or "")
    function_name = str(getattr(check, "function", "") or "")

    if operation.type == "replace_text":
        return kind in {"text_contains", "text_absent", "text_changed"} and selector == operation.selector
    if operation.type in {"set_attribute", "remove_attribute"}:
        return (
            kind in {"attribute_equals", "attribute_changed"}
            and selector == operation.selector
            and property_name == operation.attribute
        )
    if operation.type in {"set_css_declaration", "set_css_variable"}:
        return (
            kind in {"css_declaration", "css_changed"}
            and selector == operation.selector
            and property_name == operation.property
        )
    if operation.type == "update_widget_default":
        return kind == "widget_default_changed" and property_name == operation.property
    if operation.type == "replace_numeric_literal":
        return kind == "numeric_changed" and (
            (function_name and function_name == operation.function)
            or (selector and selector == operation.selector)
        )
    if operation.type == "remove_element":
        return kind in {"text_absent", "text_changed"} and selector == operation.selector
    return False


def upgrade_strategy(current: EditExecutionStrategy) -> EditExecutionStrategy | None:
    """Return the next more powerful strategy, or None when already at full regen."""

    ladder: tuple[EditExecutionStrategy, ...] = (
        "deterministic_patch",
        "scoped_model_patch",
        "full_html_regeneration",
    )
    try:
        index = ladder.index(current)
    except ValueError:
        return "full_html_regeneration"
    if index + 1 >= len(ladder):
        return None
    return ladder[index + 1]


def strategy_ladder_from(start: EditExecutionStrategy) -> tuple[EditExecutionStrategy, ...]:
    ladder: tuple[EditExecutionStrategy, ...] = (
        "deterministic_patch",
        "scoped_model_patch",
        "full_html_regeneration",
    )
    try:
        index = ladder.index(start)
    except ValueError:
        return ("full_html_regeneration",)
    return ladder[index:]


def _scoped_targets_bindable(targets: tuple[dict[str, Any], ...], business_html: str) -> bool:
    if not targets:
        return False
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(business_html or "", "html.parser")
    functions = extract_named_functions(business_html)
    bindable = 0
    for item in targets:
        selector = str(item.get("selector") or "")
        function_name = str(item.get("function") or "")
        kind = str(item.get("kind") or "")
        if kind == "function" or function_name:
            if function_name and len(functions.get(function_name, [])) == 1:
                bindable += 1
                continue
        if selector:
            try:
                if soup.select(selector):
                    bindable += 1
            except Exception:
                continue
    return bindable > 0
