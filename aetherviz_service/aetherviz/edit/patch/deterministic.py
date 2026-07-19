"""Deterministic HTML patch application for bindable EditOperations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import tinycss2
from bs4 import BeautifulSoup, NavigableString, Tag

from aetherviz_service.aetherviz.edit.spec import EditOperation
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

DEGREE_RATIOS = {
    "slight": 1.1,
    "moderate": 1.2,
    "strong": 1.5,
}

_NUMBER_UNIT_RE = re.compile(
    r"^(?P<sign>-?)(?P<number>\d+(?:\.\d+)?)(?P<unit>px|rem|em|%|s|ms|vh|vw|)$",
    re.IGNORECASE,
)
@dataclass(frozen=True)
class DeterministicPatchResult:
    html: str
    applied: tuple[str, ...]
    unresolved: tuple[str, ...] = ()


def apply_deterministic_operations(
    html: str,
    operations: tuple[EditOperation, ...] | list[EditOperation],
) -> DeterministicPatchResult:
    if not operations:
        return DeterministicPatchResult(html=html, applied=(), unresolved=("empty_operations",))

    soup = BeautifulSoup(html or "", "html.parser")
    working = html or ""
    applied: list[str] = []
    unresolved: list[str] = []

    # CSS/variable and numeric ops mutate the raw HTML string; DOM ops use soup then serialize.
    soup_dirty = False
    for index, op in enumerate(operations):
        op_id = f"{op.type}:{op.selector or op.property or op.function or index}"
        try:
            if op.type in {
                "replace_text",
                "set_attribute",
                "remove_attribute",
                "remove_element",
                "update_widget_default",
            }:
                if soup_dirty is False and working != html:
                    soup = BeautifulSoup(working, "html.parser")
                ok, reason = _apply_dom_operation(soup, op)
                if ok:
                    applied.append(op_id)
                    soup_dirty = True
                else:
                    unresolved.append(f"{op_id}:{reason}")
            elif op.type in {"set_css_declaration", "set_css_variable"}:
                if soup_dirty:
                    working = _serialize_soup(soup)
                    soup_dirty = False
                ok, reason, working = _apply_css_operation(working, op)
                if ok:
                    applied.append(op_id)
                else:
                    unresolved.append(f"{op_id}:{reason}")
            elif op.type == "replace_numeric_literal":
                if soup_dirty:
                    working = _serialize_soup(soup)
                    soup_dirty = False
                ok, reason, working = _apply_numeric_literal(working, op)
                if ok:
                    applied.append(op_id)
                else:
                    unresolved.append(f"{op_id}:{reason}")
            else:
                unresolved.append(f"{op_id}:unsupported")
        except Exception as exc:  # pragma: no cover - defensive
            unresolved.append(f"{op_id}:{type(exc).__name__}")

    if soup_dirty:
        working = _serialize_soup(soup)
    if not applied:
        return DeterministicPatchResult(html=html, applied=(), unresolved=tuple(unresolved or ["no_applied"]))
    return DeterministicPatchResult(html=working, applied=tuple(applied), unresolved=tuple(unresolved))


def resolve_relative_value(
    baseline_value: str,
    *,
    ratio: float | None = None,
    degree: str = "",
) -> str | None:
    match = _NUMBER_UNIT_RE.match((baseline_value or "").strip())
    if not match:
        return None
    factor = ratio if ratio is not None else DEGREE_RATIOS.get(degree or "", None)
    if factor is None:
        return None
    number = float(match.group("number"))
    if match.group("sign") == "-":
        number = -number
    unit = match.group("unit") or ""
    scaled = number * factor
    if unit.lower() in {"s", "ms"} or "." in match.group("number"):
        rendered = f"{scaled:.4g}"
    else:
        rendered = str(int(round(scaled))) if abs(scaled - round(scaled)) < 1e-9 else f"{scaled:.4g}"
    return f"{rendered}{unit}"


def _apply_dom_operation(soup: BeautifulSoup, op: EditOperation) -> tuple[bool, str]:
    if op.type == "update_widget_default":
        return _update_widget_default(soup, op)

    elements = _select(soup, op.selector)
    if not elements:
        return False, "selector_missing"

    if op.type == "replace_text":
        for element in elements:
            element.clear()
            element.append(NavigableString(op.value))
        return True, ""

    if op.type == "set_attribute":
        value = op.value
        if op.value_mode == "relative":
            baseline = str(elements[0].get(op.attribute) or "")
            resolved = resolve_relative_value(baseline, ratio=op.ratio, degree=op.degree)
            if resolved is None:
                return False, "relative_unresolved"
            value = resolved
        for element in elements:
            element[op.attribute] = value
        return True, ""

    if op.type == "remove_attribute":
        for element in elements:
            if op.attribute in element.attrs:
                del element[op.attribute]
        return True, ""

    if op.type == "remove_element":
        for element in elements:
            element.decompose()
        return True, ""

    return False, "unsupported"


def _apply_css_operation(html: str, op: EditOperation) -> tuple[bool, str, str]:
    if op.type == "set_css_variable":
        return _set_css_variable(html, op)

    # Prefer stylesheet rule matching selector; fall back to inline style on elements.
    style_pattern = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)
    for match in style_pattern.finditer(html):
        css_text = match.group(2)
        updated_css, changed = _set_declaration_in_stylesheet(
            css_text,
            selector=op.selector,
            property_name=op.property,
            value=op.value,
            value_mode=op.value_mode,
            ratio=op.ratio,
            degree=op.degree,
        )
        if changed:
            start, end = match.start(2), match.end(2)
            return True, "", html[:start] + updated_css + html[end:]

    soup = BeautifulSoup(html, "html.parser")
    elements = _select(soup, op.selector)
    if not elements:
        return False, "selector_missing", html
    target = elements[0]
    style_text = str(target.get("style") or "")
    new_style, changed = _set_declaration_in_list(
        style_text,
        property_name=op.property,
        value=op.value,
        value_mode=op.value_mode,
        ratio=op.ratio,
        degree=op.degree,
    )
    if not changed:
        return False, "css_unchanged_or_unresolved", html
    target["style"] = new_style
    return True, "", _serialize_soup(soup)


def _set_css_variable(html: str, op: EditOperation) -> tuple[bool, str, str]:
    property_name = op.property
    # Prefer :root / html rule, then first style block.
    style_pattern = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)
    for match in style_pattern.finditer(html):
        css_text = match.group(2)
        for selector in (":root", "html", op.selector or ":root"):
            if not selector:
                continue
            updated_css, changed = _set_declaration_in_stylesheet(
                css_text,
                selector=selector,
                property_name=property_name,
                value=op.value,
                value_mode=op.value_mode,
                ratio=op.ratio,
                degree=op.degree,
                create_if_missing=(selector in {":root", "html"}),
            )
            if changed:
                start, end = match.start(2), match.end(2)
                return True, "", html[:start] + updated_css + html[end:]
    # Append a :root rule if nothing matched.
    insertion = f":root {{ {property_name}: {op.value}; }}\n"
    style_open = re.search(r"<style\b[^>]*>", html, re.IGNORECASE)
    if style_open and op.value_mode == "absolute" and op.value:
        pos = style_open.end()
        return True, "", html[:pos] + insertion + html[pos:]
    return False, "css_variable_unresolved", html


def _set_declaration_in_stylesheet(
    css_text: str,
    *,
    selector: str,
    property_name: str,
    value: str,
    value_mode: str,
    ratio: float | None,
    degree: str,
    create_if_missing: bool = False,
) -> tuple[str, bool]:
    rules = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=False)
    changed = False
    output: list[str] = []
    found = False
    for rule in rules:
        if getattr(rule, "type", "") != "qualified-rule":
            output.append(tinycss2.serialize([rule]))
            continue
        rule_selector = tinycss2.serialize(rule.prelude).strip()
        if rule_selector != selector:
            output.append(tinycss2.serialize([rule]))
            continue
        found = True
        decls = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
        new_decls, decl_changed = _mutate_declarations(
            decls,
            property_name=property_name,
            value=value,
            value_mode=value_mode,
            ratio=ratio,
            degree=degree,
        )
        if decl_changed:
            changed = True
        body = tinycss2.serialize(new_decls)
        output.append(f"{selector} {{{body}}}")
    if not found and create_if_missing and value_mode == "absolute" and value:
        output.append(f"{selector} {{ {property_name}: {value}; }}")
        changed = True
    return "".join(output) if changed else css_text, changed


def _set_declaration_in_list(
    style_text: str,
    *,
    property_name: str,
    value: str,
    value_mode: str,
    ratio: float | None,
    degree: str,
) -> tuple[str, bool]:
    decls = tinycss2.parse_declaration_list(style_text or "", skip_comments=True, skip_whitespace=True)
    new_decls, changed = _mutate_declarations(
        decls,
        property_name=property_name,
        value=value,
        value_mode=value_mode,
        ratio=ratio,
        degree=degree,
    )
    if not changed:
        return style_text, False
    return tinycss2.serialize(new_decls).strip(), True


def _mutate_declarations(
    decls: list[Any],
    *,
    property_name: str,
    value: str,
    value_mode: str,
    ratio: float | None,
    degree: str,
) -> tuple[list[Any], bool]:
    changed = False
    result: list[Any] = []
    found = False
    for decl in decls:
        if getattr(decl, "type", "") != "declaration" or decl.name != property_name:
            result.append(decl)
            continue
        found = True
        current = tinycss2.serialize(decl.value).strip()
        if value_mode == "relative":
            resolved = resolve_relative_value(current, ratio=ratio, degree=degree)
            if resolved is None:
                result.append(decl)
                continue
            new_value = resolved
        else:
            new_value = value
        if new_value == current:
            result.append(decl)
            continue
        parsed = tinycss2.parse_declaration_list(
            f"{property_name}: {new_value};",
            skip_comments=True,
            skip_whitespace=True,
        )
        if parsed:
            result.extend(parsed)
            changed = True
        else:
            result.append(decl)
    if not found and value_mode == "absolute" and value:
        parsed = tinycss2.parse_declaration_list(
            f"{property_name}: {value};",
            skip_comments=True,
            skip_whitespace=True,
        )
        result.extend(parsed)
        changed = True
    return result, changed


def _apply_numeric_literal(html: str, op: EditOperation) -> tuple[bool, str, str]:
    if not op.function:
        return False, "missing_function", html
    if not op.property:
        return False, "missing_property", html
    functions = extract_named_functions(html)
    matches = functions.get(op.function) or []
    if len(matches) != 1:
        return False, "function_not_unique", html
    function = matches[0]
    updated_source, changed = _replace_named_number(
        function.source,
        property_name=op.property,
        value=op.value,
        value_mode=op.value_mode,
        ratio=op.ratio,
        degree=op.degree,
    )
    if not changed:
        return False, "numeric_unresolved", html
    return True, "", html[: function.start] + updated_source + html[function.end :]


def _replace_named_number(
    source: str,
    *,
    property_name: str,
    value: str,
    value_mode: str,
    ratio: float | None,
    degree: str,
) -> tuple[str, bool]:
    escaped_property = re.escape(property_name)
    assignment = re.compile(
        rf"(?P<prefix>\b{escaped_property}\b\s*(?::|=(?!=))\s*)"
        rf"(?P<number>-?\d+(?:\.\d+)?)"
    )
    match = assignment.search(source)
    if not match:
        return source, False
    if value_mode == "absolute":
        if not value:
            return source, False
        replacement = value
    else:
        resolved = resolve_relative_value(match.group("number"), ratio=ratio, degree=degree)
        if resolved is None:
            return source, False
        replacement = resolved
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", replacement):
        return source, False
    if replacement == match.group("number"):
        return source, False
    return source[: match.start("number")] + replacement + source[match.end("number") :], True


def _update_widget_default(soup: BeautifulSoup, op: EditOperation) -> tuple[bool, str]:
    script = soup.find("script", id="widget-config")
    if script is None or not isinstance(script, Tag):
        return False, "widget_config_missing"
    try:
        payload = json.loads(script.get_text() or "{}")
    except (TypeError, ValueError):
        return False, "widget_config_invalid"
    if not isinstance(payload, dict):
        return False, "widget_config_invalid"

    keys = [part for part in op.property.split(".") if part]
    if not keys:
        return False, "missing_property"
    cursor: Any = payload
    for key in keys[:-1]:
        if not isinstance(cursor, dict) or key not in cursor:
            return False, "property_path_missing"
        cursor = cursor[key]
    leaf = keys[-1]
    if not isinstance(cursor, dict) or leaf not in cursor:
        # Allow creating leaf only for absolute mode.
        if op.value_mode != "absolute" or not isinstance(cursor, dict):
            return False, "property_path_missing"
    current = cursor.get(leaf) if isinstance(cursor, dict) else None
    if op.value_mode == "relative":
        if not isinstance(current, (int, float)):
            return False, "relative_requires_number"
        factor = op.ratio if op.ratio is not None else DEGREE_RATIOS.get(op.degree or "", None)
        if factor is None:
            return False, "relative_unresolved"
        new_value: Any = current * factor
        if isinstance(current, int) and abs(new_value - round(new_value)) < 1e-9:
            new_value = int(round(new_value))
    else:
        new_value = _coerce_json_value(op.value, current)
    cursor[leaf] = new_value
    script.string = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return True, ""


def _coerce_json_value(raw: str, current: Any) -> Any:
    text = (raw or "").strip()
    if isinstance(current, bool):
        return text.lower() in {"1", "true", "yes"}
    if isinstance(current, int) and not isinstance(current, bool):
        try:
            return int(float(text))
        except ValueError:
            return text
    if isinstance(current, float):
        try:
            return float(text)
        except ValueError:
            return text
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except ValueError:
            return text
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _select(soup: BeautifulSoup, selector: str) -> list[Tag]:
    if not selector:
        return []
    try:
        return [item for item in soup.select(selector) if isinstance(item, Tag)]
    except Exception:
        return []


def _serialize_soup(soup: BeautifulSoup) -> str:
    # Prefer original doctype if present.
    html = str(soup)
    if soup.find("html") is not None and not html.lstrip().lower().startswith("<!doctype"):
        return "<!DOCTYPE html>\n" + html
    return html
