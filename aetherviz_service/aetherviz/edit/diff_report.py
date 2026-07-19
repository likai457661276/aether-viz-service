"""Deterministic semantic diff between baseline and candidate HTML for edit observability."""

from __future__ import annotations

import json
from typing import Any

import tinycss2
from bs4 import BeautifulSoup, Tag

from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions


def build_edit_diff_report(baseline_html: str, candidate_html: str) -> dict[str, Any]:
    """Build a bounded structural diff. Visual/runtime slots stay offline-only placeholders."""

    baseline_soup = BeautifulSoup(baseline_html or "", "html.parser")
    candidate_soup = BeautifulSoup(candidate_html or "", "html.parser")

    baseline_dom = _dom_index(baseline_soup)
    candidate_dom = _dom_index(candidate_soup)
    dom_added = sorted(set(candidate_dom) - set(baseline_dom))
    dom_removed = sorted(set(baseline_dom) - set(candidate_dom))
    dom_changed = sorted(
        key for key in set(baseline_dom) & set(candidate_dom) if baseline_dom[key] != candidate_dom[key]
    )

    baseline_css = _css_index(baseline_soup)
    candidate_css = _css_index(candidate_soup)
    css_changed = sorted(
        selector
        for selector in set(baseline_css) | set(candidate_css)
        if baseline_css.get(selector) != candidate_css.get(selector)
    )

    baseline_functions = extract_named_functions(baseline_html)
    candidate_functions = extract_named_functions(candidate_html)
    js_changed = sorted(
        name
        for name in set(baseline_functions) | set(candidate_functions)
        if _function_hashes(baseline_functions.get(name)) != _function_hashes(candidate_functions.get(name))
    )

    baseline_widget = _widget_snapshot(baseline_soup)
    candidate_widget = _widget_snapshot(candidate_soup)
    defaults_changed = sorted(
        key
        for key in set(baseline_widget) | set(candidate_widget)
        if key != "type" and baseline_widget.get(key) != candidate_widget.get(key)
    )
    type_changed = baseline_widget.get("type") != candidate_widget.get("type")

    change_units = len(dom_added) + len(dom_removed) + len(dom_changed) + len(css_changed) + len(js_changed)
    # Unrelated ratio is a coarse budget signal: when many units change relative to a soft cap.
    soft_cap = 20
    unrelated_change_ratio = round(min(change_units / soft_cap, 1.0), 3)

    return {
        "dom": {
            "added": dom_added[:40],
            "removed": dom_removed[:40],
            "changed": dom_changed[:40],
        },
        "css": {
            "changed_rules": css_changed[:40],
            "changed_variables": _changed_css_variables(baseline_css, candidate_css)[:20],
        },
        "javascript": {
            "changed_functions": js_changed[:40],
            "changed_state_fields": [],
            "changed_event_bindings": [],
        },
        "widget": {
            "defaults_changed": defaults_changed[:20],
            "type_changed": type_changed,
            "actions_removed": _missing_actions(baseline_html, candidate_html),
        },
        "visual": {"computed": False, "reason": "offline_only"},
        "runtime": {"computed": False, "reason": "offline_only"},
        "unrelated_change_ratio": unrelated_change_ratio,
        "change_unit_count": change_units,
    }


def _dom_index(soup: BeautifulSoup) -> dict[str, str]:
    index: dict[str, str] = {}
    for element in soup.find_all(True):
        if not isinstance(element, Tag):
            continue
        key = _element_key(element)
        if not key or key in index:
            continue
        attrs = {
            str(name): value
            for name, value in element.attrs.items()
            if name in {"id", "class", "data-role", "data-edit-role", "data-region", "style", "aria-label"}
        }
        index[key] = json.dumps(
            {"tag": element.name, "attrs": attrs, "text": element.get_text(" ", strip=True)[:120]},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        if len(index) >= 120:
            break
    return index


def _element_key(element: Tag) -> str:
    if element.get("id"):
        return f"#{element['id']}"
    if element.get("data-edit-role"):
        return f"[data-edit-role={element.get('data-edit-role')}]"
    if element.get("data-role"):
        return f"{element.name}[data-role={element.get('data-role')}]"
    if element.get("data-region"):
        return f"[data-region={element.get('data-region')}]"
    classes = [str(value) for value in (element.get("class") or [])[:2]]
    if classes:
        return f"{element.name}." + ".".join(classes)
    return ""


def _css_index(soup: BeautifulSoup) -> dict[str, str]:
    index: dict[str, str] = {}
    for style in soup.find_all("style"):
        for rule in tinycss2.parse_stylesheet(style.get_text() or "", skip_comments=True, skip_whitespace=True):
            if getattr(rule, "type", "") != "qualified-rule":
                continue
            selector = tinycss2.serialize(rule.prelude).strip()
            if not selector:
                continue
            declarations: dict[str, str] = {}
            for declaration in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
                if getattr(declaration, "type", "") != "declaration":
                    continue
                declarations[str(declaration.name)] = tinycss2.serialize(declaration.value).strip()
            index[selector] = json.dumps(declarations, ensure_ascii=False, sort_keys=True)
            if len(index) >= 80:
                return index
    return index


def _changed_css_variables(baseline: dict[str, str], candidate: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for selector in set(baseline) | set(candidate):
        before = json.loads(baseline.get(selector) or "{}")
        after = json.loads(candidate.get(selector) or "{}")
        for key in set(before) | set(after):
            if str(key).startswith("--") and before.get(key) != after.get(key):
                changed.append(f"{selector}:{key}")
    return changed


def _function_hashes(matches: list[Any] | None) -> tuple[str, ...]:
    if not matches:
        return ()
    return tuple(item.source_hash for item in matches)


def _widget_snapshot(soup: BeautifulSoup) -> dict[str, str]:
    script = soup.find("script", id="widget-config")
    if script is None:
        return {}
    try:
        payload = json.loads(script.get_text() or "{}")
    except (TypeError, ValueError):
        return {"parse_error": "true"}
    if not isinstance(payload, dict):
        return {}
    snapshot: dict[str, str] = {}
    for key, value in list(payload.items())[:30]:
        if isinstance(value, (dict, list)):
            snapshot[str(key)] = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        else:
            snapshot[str(key)] = "" if value is None else str(value)
    return snapshot


def _missing_actions(baseline_html: str, candidate_html: str) -> list[str]:
    required = (
        "SET_WIDGET_STATE",
        "HIGHLIGHT_ELEMENT",
        "ANNOTATE_ELEMENT",
        "REVEAL_ELEMENT",
    )
    return [action for action in required if action in (baseline_html or "") and action not in (candidate_html or "")]
