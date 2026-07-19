"""Inline JavaScript syntax checker."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from aetherviz_service.aetherviz.tools.javascript_syntax import check_javascript_syntax


def check_inline_javascript(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    parsed = soup or BeautifulSoup(html or "", "html.parser")
    module_scripts = [
        script for script in parsed.find_all("script") if str(script.get("type") or "").strip().lower() == "module"
    ]
    scripts = [
        script.get_text("\n", strip=False)
        for script in parsed.find_all("script")
        if _is_executable_inline_script(script)
    ]
    errors = [
        {"type": "unsupported_module_script", "message": "不支持 ES Module 脚本", "line": None}
        for _script in module_scripts
    ]
    if scripts:
        error = check_javascript_syntax("\n;\n".join(scripts))
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
    }
