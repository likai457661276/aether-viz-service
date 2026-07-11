"""HTML security checker."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.tools.security_policy import allowed_external_urls

FORBIDDEN_TAGS = {"iframe", "object", "embed", "form"}
FORBIDDEN_PATTERNS = [
    (re.compile(r"\beval\s*\(", re.IGNORECASE), "eval()"),
    (re.compile(r"\bnew\s+Function\b", re.IGNORECASE), "new Function()"),
    (re.compile(r"\bdocument\.write\s*\(", re.IGNORECASE), "document.write()"),
    (re.compile(r"(?<!['\"`@#\w])\bimport\s+(?![\w\s]*['\"`])", re.IGNORECASE), "ES Module import"),
    (re.compile(r"\brequire\s*\(", re.IGNORECASE), "CommonJS require()"),
    (re.compile(r"\bfetch\s*\(", re.IGNORECASE), "fetch()"),
    (re.compile(r"\bXMLHttpRequest\b", re.IGNORECASE), "XMLHttpRequest"),
    (re.compile(r"\bWebSocket\s*\(", re.IGNORECASE), "WebSocket"),
    (re.compile(r"\bEventSource\s*\(", re.IGNORECASE), "EventSource"),
]
def check_security(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    errors = []
    allowed_urls = {_normalize_url(url) for url in allowed_external_urls()}
    for tag in parsed.find_all(FORBIDDEN_TAGS):
        errors.append({"type": "forbidden_tag", "message": f"HTML 包含禁止标签 <{tag.name}>", "line": None})
    for tag in parsed.find_all(True):
        for attr_name, attr_value in tag.attrs.items():
            lower_name = attr_name.lower()
            value = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
            lower_value = value.lower()
            if lower_name.startswith("on"):
                errors.append({"type": "inline_event", "message": f"禁止内联事件属性 {attr_name}", "line": None})
            if "javascript:" in lower_value:
                errors.append({"type": "javascript_url", "message": "禁止 javascript: URL", "line": None})
            if lower_name in {"src", "href", "srcset", "poster"} and re.search(r"https?://", lower_value):
                normalized = _normalize_url(value)
                if (
                    normalized not in allowed_urls
                ):
                    errors.append(
                        {
                            "type": "external_resource",
                            "message": f"非白名单外部资源：{value[:120]}",
                            "line": None,
                        }
                    )
    style_text = "\n".join(style.get_text("\n", strip=False) for style in parsed.find_all("style"))
    style_text += "\n" + "\n".join(str(tag.get("style") or "") for tag in parsed.find_all(style=True))
    if re.search(r"@import\s+|url\s*\(\s*['\"]?https?://", style_text, re.IGNORECASE):
        errors.append({"type": "external_style_resource", "message": "禁止 CSS @import 或外部 URL 资源", "line": None})
    for pattern, label in FORBIDDEN_PATTERNS:
        if pattern.search(html or ""):
            errors.append({"type": "forbidden_script", "message": f"HTML 包含禁止内容：{label}", "line": None})
    return {
        "ok": not errors,
        "severity": "error" if errors else "info",
        "summary": "安全检查完成",
        "errors": errors,
        "warnings": [],
    }


def _normalize_url(url: str) -> str:
    return url.strip()
