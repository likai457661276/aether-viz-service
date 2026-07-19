"""Structured edit operations compiled from diagnosis for deterministic execution."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.limits import MAX_DETERMINISTIC_OPERATIONS
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

OperationType = Literal[
    "replace_text",
    "set_attribute",
    "remove_attribute",
    "set_css_declaration",
    "set_css_variable",
    "remove_element",
    "update_widget_default",
    "replace_numeric_literal",
]
ValueMode = Literal["absolute", "relative"]
Degree = Literal["slight", "moderate", "strong", ""]

OPERATION_TYPES = frozenset(
    {
        "replace_text",
        "set_attribute",
        "remove_attribute",
        "set_css_declaration",
        "set_css_variable",
        "remove_element",
        "update_widget_default",
        "replace_numeric_literal",
    }
)

EDIT_OPERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "type",
        "selector",
        "role",
        "property",
        "attribute",
        "function",
        "value_mode",
        "value",
        "ratio",
        "degree",
    ],
    "properties": {
        "type": {"type": "string", "enum": sorted(OPERATION_TYPES)},
        "selector": {"type": "string", "maxLength": 240},
        "role": {"type": "string", "maxLength": 80},
        "property": {"type": "string", "maxLength": 100},
        "attribute": {"type": "string", "maxLength": 100},
        "function": {"type": "string", "maxLength": 120},
        "value_mode": {"type": "string", "enum": ["absolute", "relative"]},
        "value": {"type": "string", "maxLength": 500},
        "ratio": {
            "anyOf": [
                {"type": "number", "minimum": 0.1, "maximum": 10},
                {"type": "null"},
            ]
        },
        "degree": {"type": "string", "enum": ["", "slight", "moderate", "strong"]},
    },
}


@dataclass(frozen=True)
class EditOperation:
    type: OperationType
    selector: str = ""
    role: str = ""
    property: str = ""
    attribute: str = ""
    function: str = ""
    value_mode: ValueMode = "absolute"
    value: str = ""
    ratio: float | None = None
    degree: Degree = ""

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.ratio is None:
            payload.pop("ratio", None)
            payload["ratio"] = None
        return payload


def normalize_operations(
    raw: Any,
    *,
    business_html: str,
    resolve_role_selector: Any | None = None,
) -> tuple[tuple[EditOperation, ...], tuple[str, ...]]:
    """Normalize model-emitted operations; drop unbound ones instead of hard-failing."""

    if not isinstance(raw, list):
        return (), ()
    soup = BeautifulSoup(business_html or "", "html.parser")
    functions = extract_named_functions(business_html)
    operations: list[EditOperation] = []
    dropped: list[str] = []
    for index, item in enumerate(raw[:MAX_DETERMINISTIC_OPERATIONS]):
        if not isinstance(item, dict):
            continue
        op_type = str(item.get("type") or "")
        if op_type not in OPERATION_TYPES:
            dropped.append(f"unknown_type:{op_type or index}")
            continue
        selector = str(item.get("selector") or "")[:240]
        role = str(item.get("role") or "")[:80]
        if not selector and role and callable(resolve_role_selector):
            selector = str(resolve_role_selector(role, soup) or "")[:240]
        property_name = str(item.get("property") or "")[:100]
        attribute = str(item.get("attribute") or "")[:100]
        function_name = str(item.get("function") or "")[:120]
        value_mode = str(item.get("value_mode") or "absolute")
        if value_mode not in {"absolute", "relative"}:
            value_mode = "absolute"
        value = str(item.get("value") or "")[:500]
        degree = str(item.get("degree") or "")
        if degree not in {"", "slight", "moderate", "strong"}:
            degree = ""
        ratio = _optional_float(item.get("ratio"))

        bindable, drop_reason = _is_bindable(
            op_type=op_type,  # type: ignore[arg-type]
            selector=selector,
            attribute=attribute,
            property_name=property_name,
            function_name=function_name,
            value_mode=value_mode,  # type: ignore[arg-type]
            value=value,
            ratio=ratio,
            degree=degree,  # type: ignore[arg-type]
            soup=soup,
            functions=functions,
        )
        if not bindable:
            dropped.append(f"{op_type}:{drop_reason}")
            continue
        operations.append(
            EditOperation(
                type=op_type,  # type: ignore[arg-type]
                selector=selector,
                role=role,
                property=property_name,
                attribute=attribute,
                function=function_name,
                value_mode=value_mode,  # type: ignore[arg-type]
                value=value,
                ratio=ratio,
                degree=degree,  # type: ignore[arg-type]
            )
        )
    return tuple(operations), tuple(dropped)


def operations_are_deterministic(operations: tuple[EditOperation, ...]) -> bool:
    return bool(operations) and all(op.type in OPERATION_TYPES for op in operations)


def _is_bindable(
    *,
    op_type: OperationType,
    selector: str,
    attribute: str,
    property_name: str,
    function_name: str,
    value_mode: ValueMode,
    value: str,
    ratio: float | None,
    degree: Degree,
    soup: BeautifulSoup,
    functions: dict[str, list[Any]],
) -> tuple[bool, str]:
    if op_type == "update_widget_default":
        if not property_name:
            return False, "missing_property"
        if value_mode == "absolute" and not value:
            return False, "missing_value"
        if value_mode == "relative" and ratio is None and not degree:
            return False, "missing_relative"
        return True, ""

    if op_type == "replace_numeric_literal":
        if not function_name:
            return False, "missing_function"
        if len(functions.get(function_name, [])) != 1:
            return False, "function_not_unique"
        if not property_name:
            return False, "missing_property"
        if value_mode == "absolute" and not _is_numeric_literal(value):
            return False, "invalid_numeric_value"
        if value_mode == "relative" and ratio is None and not degree:
            return False, "missing_relative"
        return True, ""

    if op_type == "set_css_variable":
        if not property_name.startswith("--"):
            return False, "invalid_css_variable"
        if value_mode == "absolute" and not value:
            return False, "missing_value"
        if value_mode == "relative" and ratio is None and not degree:
            return False, "missing_relative"
        return True, ""

    if not selector or not _selector_exists(soup, selector):
        return False, "selector_missing"

    if op_type == "replace_text":
        if value_mode != "absolute" or not value:
            return False, "missing_text"
        return True, ""
    if op_type == "set_attribute":
        if not attribute:
            return False, "missing_attribute"
        if value_mode == "absolute" and value == "" and attribute not in {"disabled", "hidden"}:
            return False, "missing_value"
        return True, ""
    if op_type == "remove_attribute":
        return (bool(attribute), "missing_attribute" if not attribute else "")
    if op_type == "set_css_declaration":
        if not property_name:
            return False, "missing_property"
        if value_mode == "absolute" and not value:
            return False, "missing_value"
        if value_mode == "relative" and ratio is None and not degree:
            return False, "missing_relative"
        return True, ""
    if op_type == "remove_element":
        return True, ""
    return False, "unsupported"


def _selector_exists(soup: BeautifulSoup, selector: str) -> bool:
    if not selector or selector.startswith(".av-") or selector.startswith("#aetherviz-app-shell"):
        return False
    try:
        return bool(soup.select(selector))
    except Exception:
        return False


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0.1 or number > 10:
        return None
    return number


def _is_numeric_literal(value: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", (value or "").strip()))
