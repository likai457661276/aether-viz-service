"""Deterministic, bounded context extraction for HTML edit diagnosis."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import tinycss2
from bs4 import BeautifulSoup, Tag

from aetherviz_service.aetherviz.tools.function_patch import extract_named_functions

MAX_DOM_TARGETS = 60
MAX_CSS_RULES = 60
MAX_FUNCTIONS = 60
MAX_CONTEXT_MESSAGES = 4
MAX_EDIT_CONTEXT_CHARS = 24_000

SERVER_LAYOUT_TARGETS = (
    "外壳",
    "app shell",
    "app-shell",
    "aetherviz-app-shell",
    "控制面板",
    "实验控制",
    "右侧面板",
    "右侧栏",
    "侧边栏",
    "侧栏",
    "左右栏",
    "页面网格",
    "整页布局",
    "页面布局",
    "页面滚动",
    "响应式断点",
)
SERVER_LAYOUT_CHANGES = (
    "宽度",
    "高度",
    "太宽",
    "太窄",
    "挤压",
    "拥挤",
    "间距",
    "布局",
    "分栏",
    "位置",
    "移动到",
    "放到",
    "滚动",
    "溢出",
    "断点",
)


def is_server_layout_request(message: str) -> bool:
    normalized = " ".join((message or "").lower().split())
    return bool(normalized) and any(target in normalized for target in SERVER_LAYOUT_TARGETS) and any(
        change in normalized for change in SERVER_LAYOUT_CHANGES
    )


def build_edit_context_summary(
    *,
    instruction: str,
    business_html: str,
    context: dict[str, Any] | None,
    validation_report: dict[str, Any] | None,
    edit_target: dict[str, Any] | None = None,
    runtime_error: dict[str, Any] | None = None,
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
        },
        "request_context": _request_context(context),
        "edit_target": _edit_target(resolved_target),
        "runtime_error": _runtime_error(resolved_runtime_error),
        "validation": _validation_summary(validation_report),
        "ownership": {
            "deterministic_server_layout_match": is_server_layout_request(instruction),
            "server_owned_selectors": ["#aetherviz-app-shell", ".av-*", "[data-aetherviz-shell]"],
            "rule": "math-shell-v1 与 .av-* 属于服务端；业务 HTML、主视觉、业务控件和运行时可编辑",
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
    if not isinstance(context, dict):
        return {}
    plan = _mapping(context.get("plan_summary"))
    selected = _mapping(context.get("selected_file"))
    memory = _mapping(context.get("memory"))
    recent = context.get("recent_messages") if isinstance(context.get("recent_messages"), list) else []
    return {
        "topic": _compact_text(context.get("topic"), 200),
        "selected_file": {
            key: selected.get(key)
            for key in ("id", "title", "topic", "html_size")
            if selected.get(key) is not None
        },
        "plan": {
            key: _bounded_value(plan.get(key))
            for key in ("title", "goal", "interactive_type", "subject", "stage_layout")
            if plan.get(key) is not None
        },
        "memory_summary": _compact_text(memory.get("summary"), 500),
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
        "computed_styles": {
            _compact_text(key, 80): _compact_text(raw, 160)
            for key, raw in list(styles.items())[:20]
        },
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
        return {
            _compact_text(key, 80): _bounded_value(raw, depth=depth + 1)
            for key, raw in list(value.items())[:20]
        }
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
