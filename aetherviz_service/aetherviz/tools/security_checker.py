"""HTML security checker."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from aetherviz_service.aetherviz.constants import get_gsap_core_cdn_url
from aetherviz_service.aetherviz.tools.security_policy import ALLOWED_EXTERNAL_URLS, KATEX_URL_PATTERN

FORBIDDEN_TAGS = {"iframe", "object", "embed", "form"}
FORBIDDEN_PATTERNS = [
    (re.compile(r"\beval\s*\(", re.IGNORECASE), "eval()"),
    (re.compile(r"\bnew\s+Function\b", re.IGNORECASE), "new Function()"),
    (re.compile(r"\bdocument\.write\s*\(", re.IGNORECASE), "document.write()"),
    (re.compile(r"(?<!['\"`@#\w])\bimport\s+(?![\w\s]*['\"`])", re.IGNORECASE), "ES Module import"),
    (re.compile(r"\brequire\s*\(", re.IGNORECASE), "CommonJS require()"),
]
def check_security(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    errors = []
    configured_gsap_url = _normalize_url(get_gsap_core_cdn_url())
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
            if lower_name in {"src", "href"} and re.search(r"https?://", lower_value):
                normalized = _normalize_url(value)
                if (
                    normalized not in ALLOWED_EXTERNAL_URLS
                    and normalized != configured_gsap_url
                    and not KATEX_URL_PATTERN.match(normalized)
                ):
                    errors.append(
                        {
                            "type": "external_resource",
                            "message": f"非白名单外部资源：{value[:120]}",
                            "line": None,
                        }
                    )
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
    parsed = urlsplit(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
