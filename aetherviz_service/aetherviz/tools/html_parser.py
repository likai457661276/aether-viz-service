"""HTML parser checker."""

from __future__ import annotations

from bs4 import BeautifulSoup, Doctype


def check_html_structure(html: str, *, soup: BeautifulSoup | None = None) -> dict:
    stripped = (html or "").strip()
    parsed = soup or BeautifulSoup(stripped, "html.parser")
    errors = []
    if not stripped:
        errors.append({"type": "empty_html", "message": "HTML 不能为空", "line": None})
    if stripped and not stripped.lower().startswith("<!doctype html>"):
        errors.append({"type": "missing_doctype_prefix", "message": "HTML 必须以 <!DOCTYPE html> 开始", "line": 1})
    if stripped and not stripped.lower().endswith("</html>"):
        errors.append({"type": "missing_html_close", "message": "HTML 必须以 </html> 结束", "line": None})
    if stripped and not any(isinstance(item, Doctype) for item in parsed.contents):
        errors.append({"type": "missing_doctype", "message": "HTML 缺少 DOCTYPE", "line": 1})
    for tag in ("html", "body", "script"):
        if parsed.find(tag) is None:
            errors.append({"type": "missing_tag", "message": f"HTML 缺少 <{tag}>", "line": None})
    return {
        "ok": not errors,
        "severity": "error" if errors else "info",
        "summary": "HTML 结构检查完成",
        "errors": errors,
        "warnings": [],
    }
