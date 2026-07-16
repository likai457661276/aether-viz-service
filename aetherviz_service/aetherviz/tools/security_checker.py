"""HTML security checker."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.tools.external_url import normalize_allowed_external_url
from aetherviz_service.aetherviz.tools.security_policy import (
    normalized_allowed_external_urls,
)

FORBIDDEN_TAGS = {"iframe", "object", "embed", "form"}
FORBIDDEN_PATTERNS = [
    (re.compile(r"\beval\s*\(", re.IGNORECASE), "eval()"),
    (re.compile(r"\bnew\s+Function\b", re.IGNORECASE), "new Function()"),
    (re.compile(r"\bdocument\.write\s*\(", re.IGNORECASE), "document.write()"),
    (re.compile(r"\bimport\s*(?:\(|[\s{*])", re.IGNORECASE), "ES Module import"),
    (re.compile(r"\brequire\s*\(", re.IGNORECASE), "CommonJS require()"),
    (re.compile(r"\bfetch\s*\(", re.IGNORECASE), "fetch()"),
    (re.compile(r"\bXMLHttpRequest\b", re.IGNORECASE), "XMLHttpRequest"),
    (re.compile(r"\bWebSocket\s*\(", re.IGNORECASE), "WebSocket"),
    (re.compile(r"\bEventSource\s*\(", re.IGNORECASE), "EventSource"),
]
_RESOURCE_ATTRIBUTES = {"src", "href", "srcset", "poster"}


def check_security(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    errors = []
    allowed_urls = normalized_allowed_external_urls()
    for tag in parsed.find_all(FORBIDDEN_TAGS):
        errors.append({"type": "forbidden_tag", "message": f"HTML 包含禁止标签 <{tag.name}>", "line": None})
    for tag in parsed.find_all(True):
        for attr_name, attr_value in tag.attrs.items():
            lower_name = attr_name.lower()
            value = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
            if lower_name.startswith("on"):
                errors.append({"type": "inline_event", "message": f"禁止内联事件属性 {attr_name}", "line": None})
            if lower_name in _RESOURCE_ATTRIBUTES:
                for resource_url in _resource_urls(lower_name, value):
                    error_type = _resource_error_type(resource_url, allowed_urls)
                    if error_type:
                        message = "禁止 javascript: URL" if error_type == "javascript_url" else f"非白名单外部资源：{resource_url[:120]}"
                        errors.append({"type": error_type, "message": message, "line": None})
    style_text = "\n".join(style.get_text("\n", strip=False) for style in parsed.find_all("style"))
    style_text += "\n" + "\n".join(str(tag.get("style") or "") for tag in parsed.find_all(style=True))
    css_urls = re.findall(r"url\s*\(\s*['\"]?([^'\")\s]+)", style_text, re.IGNORECASE)
    if re.search(r"@import\s+", style_text, re.IGNORECASE) or any(
        _resource_error_type(url, allowed_urls) for url in css_urls
    ):
        errors.append({"type": "external_style_resource", "message": "禁止 CSS @import 或外部 URL 资源", "line": None})
    executable_scripts = "\n".join(
        script.get_text("\n", strip=False)
        for script in parsed.find_all("script")
        if not script.get("src")
        and str(script.get("type") or "").strip().lower()
        not in {"application/json", "application/ld+json"}
    )
    for pattern, label in FORBIDDEN_PATTERNS:
        if pattern.search(executable_scripts):
            errors.append({"type": "forbidden_script", "message": f"HTML 包含禁止内容：{label}", "line": None})
    return {
        "ok": not errors,
        "severity": "error" if errors else "info",
        "summary": "安全检查完成",
        "errors": errors,
        "warnings": [],
    }


def _resource_urls(attribute: str, value: str) -> tuple[str, ...]:
    if attribute != "srcset":
        return (value.strip(),)
    return tuple(candidate.strip().split()[0] for candidate in value.split(",") if candidate.strip())


def _resource_error_type(value: str, allowed_urls: set[str]) -> str | None:
    compact = re.sub(r"[\x00-\x20\x7f]+", "", value or "")
    parsed = urlsplit(compact)
    scheme = parsed.scheme.lower()
    if scheme == "javascript":
        return "javascript_url"
    if compact.startswith("//") or scheme:
        if scheme != "https":
            return "external_resource"
        try:
            normalized = normalize_allowed_external_url(compact)
        except ValueError:
            return "external_resource"
        return None if normalized in allowed_urls else "external_resource"
    return None
