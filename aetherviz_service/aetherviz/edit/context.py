"""Deterministic, bounded context extraction for HTML edit diagnosis."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import tinycss2
from bs4 import BeautifulSoup, Tag

from aetherviz_service.aetherviz.edit.targeting import build_role_hints
from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.aetherviz.workflow.plan_detection import VALID_INTERACTIVE_TYPES

MAX_DOM_TARGETS = 60
MAX_CSS_RULES = 60
MAX_FUNCTIONS = 60
MAX_CONTEXT_MESSAGES = 4
MAX_EDIT_CONTEXT_CHARS = 24_000


def build_edit_assembly_plan(html: str, topic: str) -> dict[str, Any]:
    """Derive a minimal assembly/validation plan from the current HTML.

    Edit must not re-infer interactive_type from topic keywords (that can flip
    diagram pages to simulation and harden animation checks incorrectly). Prefer
    widget-config.type and shell content metadata already present in the page.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    raw: dict[str, Any] = {}
    interactive_type = _widget_interactive_type(soup)
    if interactive_type:
        raw["interactive_type"] = interactive_type
    shell_overrides = _shell_metadata_from_html(soup)
    raw.update(shell_overrides)
    return normalize_plan(raw, topic)


def _widget_interactive_type(soup: BeautifulSoup) -> str | None:
    script = soup.find("script", id="widget-config")
    if script is None:
        return None
    try:
        payload = json.loads(script.get_text())
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    value = str(payload.get("type") or payload.get("widget_type") or "").strip()
    return value if value in VALID_INTERACTIVE_TYPES else None


def _shell_metadata_from_html(soup: BeautifulSoup) -> dict[str, Any]:
    region = soup.select_one('[data-shell-content-edit="true"]')
    if isinstance(region, Tag):
        overrides: dict[str, Any] = {}
        title = str(region.get("data-title") or "").strip()
        goal = str(region.get("data-goal") or "").strip()
        objectives = [
            item.get_text(" ", strip=True)[:300]
            for item in region.select("li")
            if item.get_text(strip=True)
        ]
        if title:
            overrides["title"] = title[:160]
        if goal:
            overrides["goal"] = goal[:500]
        if objectives:
            overrides["key_points"] = objectives[:3]
        return overrides
    title_el = soup.select_one(".av-title")
    goal_el = soup.select_one(".av-goal")
    overrides = {}
    if title_el is not None and title_el.get_text(strip=True):
        overrides["title"] = title_el.get_text(" ", strip=True)[:160]
    if goal_el is not None and goal_el.get_text(strip=True):
        overrides["goal"] = goal_el.get_text(" ", strip=True)[:500]
    objectives = [item.get_text(" ", strip=True)[:300] for item in soup.select(".av-objectives li") if item.get_text(strip=True)]
    if objectives:
        overrides["key_points"] = objectives[:3]
    return overrides


def build_edit_context_summary(
    *,
    instruction: str,
    business_html: str,
    context: dict[str, Any] | None,
    validation_report: dict[str, Any] | None,
    edit_target: dict[str, Any] | None = None,
    runtime_error: dict[str, Any] | None = None,
    deterministic_pre_repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    soup = BeautifulSoup(business_html or "", "html.parser")
    resolved_target = edit_target or _mapping((context or {}).get("edit_target"))
    resolved_runtime_error = runtime_error or _mapping((context or {}).get("runtime_error"))
    summary = {
        "instruction": _compact_text(instruction, 1200),
        "document": {
            "chars": len(business_html),
            "dom_targets": _dom_targets(soup),
            "css_rules": _css_rules(soup),
            "functions": _function_inventory(business_html),
            "event_bindings": _event_bindings(business_html),
            "widget_config": _widget_config(soup),
            "role_hints": build_role_hints(soup, instruction=instruction),
        },
        "request_context": _request_context(context),
        "edit_target": _edit_target(resolved_target),
        "runtime_error": _runtime_error(resolved_runtime_error),
        "deterministic_pre_repair": _mapping(deterministic_pre_repair),
        "validation": _validation_summary(validation_report),
        "ownership": {
            "server_owned_selectors": ["#aetherviz-app-shell", ".av-*", "[data-aetherviz-shell]"],
            "rule": "math-shell-v1 与 .av-* 由服务端重建；编辑以当前 HTML 为唯一事实基线，忽略 plan_summary",
        },
    }
    return _fit_context_budget(summary)


def _dom_targets(soup: BeautifulSoup) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for element in soup.find_all(True):
        if len(result) >= MAX_DOM_TARGETS:
            break
        selector = _selector_for(element)
        text = _compact_text(element.get_text(" ", strip=True), 100)
        data_role = str(element.get("data-role") or "")
        element_id = str(element.get("id") or "")
        classes = [str(value) for value in (element.get("class") or [])[:4]]
        if not (selector or text or data_role or element_id):
            continue
        signature = _element_signature(element)
        result.append(
            {
                "selector": selector,
                "tag": element.name,
                "id": element_id,
                "classes": classes,
                "data_role": data_role,
                "text": text,
                "source_hash": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16],
            }
        )
    return result


def _selector_for(element: Tag) -> str:
    if element.get("id"):
        return f"#{element['id']}"
    if element.get("data-role"):
        return f'{element.name}[data-role="{element["data-role"]}"]'
    classes = [str(value) for value in (element.get("class") or [])[:2] if str(value)]
    if classes:
        return f"{element.name}." + ".".join(classes)
    return element.name if element.name in {"button", "svg", "canvas", "main", "section"} else ""


def _element_signature(element: Tag) -> str:
    attrs = {
        str(key): value
        for key, value in element.attrs.items()
        if key in {"id", "class", "data-role", "name", "type", "aria-label"}
    }
    return json.dumps(
        {"tag": element.name, "attrs": attrs, "text": _compact_text(element.get_text(" ", strip=True), 160)},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _css_rules(soup: BeautifulSoup) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for style in soup.find_all("style"):
        for rule in tinycss2.parse_stylesheet(style.get_text() or "", skip_comments=True, skip_whitespace=True):
            if getattr(rule, "type", "") != "qualified-rule":
                continue
            selector = tinycss2.serialize(rule.prelude).strip()
            declarations: dict[str, str] = {}
            for declaration in tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True):
                if getattr(declaration, "type", "") != "declaration":
                    continue
                declarations[str(declaration.name)] = _compact_text(tinycss2.serialize(declaration.value).strip(), 120)
                if len(declarations) >= 10:
                    break
            if selector:
                result.append({"selector": _compact_text(selector, 180), "declarations": declarations})
            if len(result) >= MAX_CSS_RULES:
                return result
    return result


def _function_inventory(html: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name, matches in extract_named_functions(html).items():
        for function in matches[:2]:
            result.append(
                {
                    "name": name,
                    "source_hash": function.source_hash,
                    "chars": len(function.source),
                    "unique": len(matches) == 1,
                }
            )
            if len(result) >= MAX_FUNCTIONS:
                return result
    return result


def _event_bindings(html: str) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    pattern = re.compile(
        r"(?P<target>[A-Za-z_$][\w$]*|document|window)\.addEventListener\(\s*['\"](?P<event>[\w:-]+)['\"]\s*,\s*(?P<handler>[A-Za-z_$][\w$]*)",
    )
    for match in pattern.finditer(html or ""):
        bindings.append(match.groupdict())
        if len(bindings) >= 30:
            break
    return bindings


def _widget_config(soup: BeautifulSoup) -> dict[str, Any]:
    script = soup.find("script", id="widget-config")
    if script is None:
        return {}
    try:
        value = json.loads(script.get_text())
    except (TypeError, ValueError):
        return {"parse_error": True}
    if not isinstance(value, dict):
        return {}
    return {
        key: _bounded_value(value.get(key))
        for key in ("type", "concept", "initial_state", "animation_config")
        if key in value
    }


def _request_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """Build edit request context without plan or plan-era memory semantics.

    Edit is HTML-baseline only. Client plan_summary and teaching-plan memory
    summaries are dropped so stale plans cannot override the current page.
    recent_messages remain for deictic resolution only.
    """
    if not isinstance(context, dict):
        return {}
    selected = _mapping(context.get("selected_file"))
    recent = context.get("recent_messages") if isinstance(context.get("recent_messages"), list) else []
    return {
        "topic": _compact_text(context.get("topic"), 200),
        "selected_file": {
            key: selected.get(key) for key in ("id", "title", "topic", "html_size") if selected.get(key) is not None
        },
        "recent_messages": [
            {
                "role": _compact_text(item.get("role"), 20),
                "content": _compact_text(item.get("content"), 300),
            }
            for item in recent[-MAX_CONTEXT_MESSAGES:]
            if isinstance(item, dict)
        ],
    }


def _edit_target(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    styles = _mapping(value.get("computed_styles"))
    return {
        "selector": _compact_text(value.get("selector"), 240),
        "text": _compact_text(value.get("text"), 300),
        "source_hash": _compact_text(value.get("source_hash"), 80),
        "computed_styles": {_compact_text(key, 80): _compact_text(raw, 160) for key, raw in list(styles.items())[:20]},
    }


def _runtime_error(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    return {
        "message": _compact_text(value.get("message"), 800),
        "detail": _compact_text(value.get("detail"), 800),
        "kind": _compact_text(value.get("kind"), 80),
        "source": _compact_text(value.get("source"), 300),
        "line": _safe_int(value.get("line")),
        "column": _safe_int(value.get("column")),
        "stack": _compact_text(value.get("stack"), 2400),
        "action": _compact_text(value.get("action"), 120),
    }


def _validation_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    return {
        "ok": bool(report.get("ok")),
        "errors": [
            {
                "type": _compact_text(item.get("type"), 100),
                "message": _compact_text(item.get("message"), 400),
                "function": _compact_text(item.get("function"), 120),
                "call_chain": item.get("call_chain", [])[:6] if isinstance(item.get("call_chain"), list) else [],
            }
            for item in report.get("errors", [])[:8]
            if isinstance(item, dict)
        ],
        "warnings": [
            {
                "type": _compact_text(item.get("type"), 100),
                "message": _compact_text(item.get("message"), 300),
            }
            for item in report.get("warnings", [])[:6]
            if isinstance(item, dict)
        ],
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 2:
        return _compact_text(value, 200)
    if isinstance(value, dict):
        return {_compact_text(key, 80): _bounded_value(raw, depth=depth + 1) for key, raw in list(value.items())[:20]}
    if isinstance(value, list):
        return [_bounded_value(item, depth=depth + 1) for item in value[:8]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _compact_text(value, 300)


def _fit_context_budget(summary: dict[str, Any]) -> dict[str, Any]:
    document = _mapping(summary.get("document"))
    collections = [
        document.get("css_rules") if isinstance(document.get("css_rules"), list) else [],
        document.get("dom_targets") if isinstance(document.get("dom_targets"), list) else [],
        document.get("functions") if isinstance(document.get("functions"), list) else [],
        document.get("event_bindings") if isinstance(document.get("event_bindings"), list) else [],
        document.get("role_hints") if isinstance(document.get("role_hints"), list) else [],
    ]
    current_chars = len(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), default=str))
    truncated = False
    while current_chars > MAX_EDIT_CONTEXT_CHARS and any(collection for collection in collections):
        largest = max(collections, key=len)
        if largest:
            largest.pop()
            truncated = True
        current_chars = len(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), default=str))
    summary["summary_chars"] = current_chars
    summary["summary_truncated"] = truncated or current_chars > MAX_EDIT_CONTEXT_CHARS
    return summary
