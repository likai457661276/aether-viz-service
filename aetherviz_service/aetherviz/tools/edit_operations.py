"""Small, deterministic HTML edit operations with bounded scope."""

from __future__ import annotations

import html as html_module
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import tinycss2
from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.agents.edit_diagnosis_agent import EditDiagnosis
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

_CSS_PROPERTY_RE = re.compile(r"^--?[A-Za-z][\w-]*$|^[A-Za-z][\w-]*$")
_ATTRIBUTE_RE = re.compile(r"^(?:aria-[\w-]+|data-[\w-]+|title|alt|value|placeholder)$")


@dataclass(frozen=True)
class EditOperationResult:
    html: str
    applied: tuple[str, ...]
    errors: tuple[str, ...] = ()
    guard: Callable[[str], list[str]] | None = None


def apply_diagnosed_operations(html: str, diagnosis: EditDiagnosis) -> EditOperationResult:
    if diagnosis.strategy not in {"css_declaration", "text_or_attribute"}:
        return EditOperationResult(html, (), ("unsupported_local_strategy",))
    updated = html
    applied: list[str] = []
    checks: list[dict[str, str]] = []
    errors: list[str] = []
    allowed_selectors = {
        str(item.get("selector") or "")
        for item in diagnosis.targets
        if str(item.get("selector") or "")
    }
    for index, operation in enumerate(diagnosis.operations):
        op = operation.get("op", "")
        selector = operation.get("selector", "")
        if selector not in allowed_selectors:
            errors.append(f"operation_selector_not_diagnosed:{selector or index}")
            continue
        if op == "set_css":
            result, check, error = _set_css(updated, operation)
        elif op == "replace_text":
            result, check, error = _replace_text(updated, operation)
        elif op == "set_attribute":
            result, check, error = _set_attribute(updated, operation)
        else:
            result, check, error = updated, {}, f"operation_not_allowed:{op or index}"
        if error:
            errors.append(error)
            continue
        updated = result
        checks.append(check)
        applied.append(f"{op}:{operation.get('selector') or index}")
    if errors or not applied:
        return EditOperationResult(html, (), tuple(errors or ["no_local_operation_applied"]))

    def guard(candidate: str) -> list[str]:
        return _verify_checks(candidate, checks)

    guard_errors = guard(updated)
    if guard_errors:
        return EditOperationResult(html, (), tuple(guard_errors))
    return EditOperationResult(updated, tuple(applied), guard=guard)


def build_diagnosis_guard(diagnosis: EditDiagnosis, source_html: str = "") -> Callable[[str], list[str]]:
    assertions = tuple(diagnosis.assertions)
    original_function_hashes = {
        str(item.get("function") or ""): str(item.get("source_hash") or "")
        for item in diagnosis.targets
        if item.get("function") and item.get("source_hash")
    }

    def guard(candidate: str) -> list[str]:
        soup = BeautifulSoup(candidate or "", "html.parser")
        errors: list[str] = []
        for assertion in assertions:
            assertion_type = assertion.get("type", "")
            selector = assertion.get("selector", "")
            elements = _select(soup, selector)
            if assertion_type == "selector_exists" and not elements:
                errors.append(f"assertion_selector_missing:{selector}")
            elif assertion_type == "text_contains":
                expected = assertion.get("expected", "")
                if not elements or not any(expected in element.get_text(" ", strip=True) for element in elements):
                    errors.append(f"assertion_text_missing:{selector}:{expected}")
            elif assertion_type == "attribute_equals":
                attribute = assertion.get("property", "")
                expected = assertion.get("expected", "")
                if not elements or not any(str(element.get(attribute) or "") == expected for element in elements):
                    errors.append(f"assertion_attribute_mismatch:{selector}:{attribute}")
            elif assertion_type == "css_declaration":
                property_name = assertion.get("property", "")
                expected = assertion.get("expected", "")
                if not _has_css_declaration(soup, selector, property_name, expected):
                    errors.append(f"assertion_css_mismatch:{selector}:{property_name}")
        if diagnosis.strategy == "function_repair" and source_html:
            candidate_functions = extract_named_functions(candidate)
            for function_name, source_hash in original_function_hashes.items():
                matches = candidate_functions.get(function_name, [])
                if len(matches) != 1 or matches[0].source_hash == source_hash:
                    errors.append(f"edit_function_not_changed:{function_name}")
        return errors

    return guard


def _set_css(source: str, operation: dict[str, str]) -> tuple[str, dict[str, str], str]:
    selector = operation.get("selector", "").strip()
    property_name = operation.get("property", "").strip()
    value = operation.get("value", "").strip()
    soup = BeautifulSoup(source or "", "html.parser")
    matches = _select(soup, selector)
    if not _safe_business_selector(selector) or not matches or len(matches) > 8:
        return source, {}, f"css_selector_invalid_or_missing:{selector}"
    if not _CSS_PROPERTY_RE.fullmatch(property_name) or property_name.lower().startswith(("behavior", "-moz-binding")):
        return source, {}, f"css_property_not_allowed:{property_name}"
    if not value or len(value) > 300 or any(
        token in value.lower() for token in ("</style", "javascript:", "expression(", "@import", "url(")
    ):
        return source, {}, f"css_value_not_allowed:{property_name}"
    if any(character in value for character in "{};"):
        return source, {}, f"css_value_not_allowed:{property_name}"
    override = f"\n/* aetherviz-edit */\n{selector}{{{property_name}:{value};}}\n"
    match = list(re.finditer(r"</style\s*>", source, re.IGNORECASE))
    if match:
        position = match[-1].start()
        updated = source[:position] + override + source[position:]
    else:
        head_end = re.search(r"</head\s*>", source, re.IGNORECASE)
        if not head_end:
            return source, {}, "missing_head_for_css_operation"
        position = head_end.start()
        updated = source[:position] + f"<style>{override}</style>\n" + source[position:]
    return updated, {"type": "css_source", "needle": override.strip()}, ""


def _replace_text(source: str, operation: dict[str, str]) -> tuple[str, dict[str, str], str]:
    selector = operation.get("selector", "").strip()
    old_text = operation.get("old_text", "")
    new_text = operation.get("new_text", "")
    soup = BeautifulSoup(source or "", "html.parser")
    elements = _select(soup, selector)
    if not _safe_business_selector(selector) or len(elements) != 1:
        return source, {}, f"text_selector_not_unique:{selector}"
    if not old_text or not new_text or "<" in old_text or len(new_text) > 500:
        return source, {}, "text_operation_invalid"
    element = elements[0]
    matching_nodes = [node for node in element.find_all(string=True) if str(node) == old_text]
    if len(matching_nodes) != 1 or source.count(old_text) != 1:
        return source, {}, "text_source_not_unique"
    escaped = html_module.escape(new_text, quote=False)
    updated = source.replace(old_text, escaped, 1)
    return updated, {"type": "text", "selector": selector, "expected": new_text}, ""


def _set_attribute(source: str, operation: dict[str, str]) -> tuple[str, dict[str, str], str]:
    selector = operation.get("selector", "").strip()
    attribute = operation.get("attribute", "").strip()
    value = operation.get("value", "").strip()
    soup = BeautifulSoup(source or "", "html.parser")
    elements = _select(soup, selector)
    if not _safe_business_selector(selector) or len(elements) != 1:
        return source, {}, f"attribute_selector_not_unique:{selector}"
    if not _ATTRIBUTE_RE.fullmatch(attribute) or len(value) > 300:
        return source, {}, f"attribute_not_allowed:{attribute}"
    original_tag = str(elements[0])
    if source.count(original_tag) != 1:
        return source, {}, "attribute_source_not_unique"
    fragment = BeautifulSoup(original_tag, "html.parser")
    target = fragment.find(True)
    if target is None:
        return source, {}, "attribute_target_missing"
    target[attribute] = value
    updated = source.replace(original_tag, str(target), 1)
    return updated, {"type": "attribute", "selector": selector, "property": attribute, "expected": value}, ""


def _verify_checks(candidate: str, checks: list[dict[str, str]]) -> list[str]:
    soup = BeautifulSoup(candidate or "", "html.parser")
    errors: list[str] = []
    for check in checks:
        if check.get("type") == "css_source":
            if check.get("needle", "") not in candidate:
                errors.append("edit_css_operation_lost")
        elif check.get("type") == "text":
            selector = check.get("selector", "")
            expected = check.get("expected", "")
            elements = _select(soup, selector)
            if not elements or not any(expected in element.get_text(" ", strip=True) for element in elements):
                errors.append(f"edit_text_operation_lost:{selector}")
        elif check.get("type") == "attribute":
            selector = check.get("selector", "")
            attribute = check.get("property", "")
            expected = check.get("expected", "")
            elements = _select(soup, selector)
            if not elements or not any(str(element.get(attribute) or "") == expected for element in elements):
                errors.append(f"edit_attribute_operation_lost:{selector}:{attribute}")
    return errors


def _safe_business_selector(selector: str) -> bool:
    lowered = selector.lower()
    return bool(selector) and lowered not in {"*", "html", "body", ":root"} and len(selector) <= 240 and "{" not in selector and "}" not in selector and not (
        lowered.startswith(".av-")
        or lowered.startswith("#aetherviz-app-shell")
        or "[data-aetherviz-shell" in lowered
    )


def _select(soup: BeautifulSoup, selector: str) -> list[Any]:
    try:
        return list(soup.select(selector)) if selector else []
    except Exception:
        return []


def _has_css_declaration(soup: BeautifulSoup, selector: str, property_name: str, expected: str) -> bool:
    for style in soup.find_all("style"):
        for rule in tinycss2.parse_stylesheet(style.get_text() or "", skip_comments=True, skip_whitespace=True):
            if getattr(rule, "type", "") != "qualified-rule":
                continue
            if tinycss2.serialize(rule.prelude).strip() != selector:
                continue
            for declaration in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
                if getattr(declaration, "type", "") != "declaration" or declaration.name != property_name:
                    continue
                if tinycss2.serialize(declaration.value).strip() == expected:
                    return True
    return False
