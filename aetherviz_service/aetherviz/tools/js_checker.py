"""Inline JavaScript syntax checker."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from aetherviz_service.aetherviz.validator import _check_javascript_syntax


def check_inline_javascript(html: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    scripts = [
        script.get_text("\n", strip=False)
        for script in soup.find_all("script")
        if _is_executable_inline_script(script)
    ]
    errors = []
    if scripts:
        error = _check_javascript_syntax("\n;\n".join(scripts))
        if error:
            errors.append({"type": "js_syntax", "message": error, "line": None})
    return {
        "ok": not errors,
        "severity": "error" if errors else "info",
        "summary": "JS 语法检查完成",
        "errors": errors,
        "warnings": [],
    }


def _is_executable_inline_script(script: Tag) -> bool:
    if script.get("src"):
        return False
    script_type = str(script.get("type", "")).strip().lower()
    return not script_type or script_type in {
        "text/javascript",
        "application/javascript",
        "application/ecmascript",
        "text/ecmascript",
        "module",
    }
