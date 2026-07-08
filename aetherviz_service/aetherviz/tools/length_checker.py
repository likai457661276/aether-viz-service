"""HTML length checker."""

from __future__ import annotations

from aetherviz_service.aetherviz.constants import HTML_OUTPUT_HARD_LIMIT_CHARS

TARGET_LIMIT_CHARS = 36000


def check_length(html: str) -> dict:
    length = len(html or "")
    errors = []
    warnings = []
    if length > HTML_OUTPUT_HARD_LIMIT_CHARS:
        errors.append(
            {
                "type": "html_length_hard_limit",
                "message": f"HTML 长度 {length} 超过硬上限 {HTML_OUTPUT_HARD_LIMIT_CHARS}",
                "line": None,
            }
        )
    elif length > TARGET_LIMIT_CHARS:
        warnings.append(
            {
                "type": "html_length_target",
                "message": f"HTML 长度 {length} 超过目标值 {TARGET_LIMIT_CHARS}",
                "line": None,
            }
        )
    return {
        "ok": not errors,
        "severity": "error" if errors else "warning" if warnings else "info",
        "summary": "长度检查完成",
        "errors": errors,
        "warnings": warnings,
    }
