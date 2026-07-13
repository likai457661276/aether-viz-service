"""HTML length checker."""

from __future__ import annotations

from aetherviz_service.aetherviz.constants import (
    ASSEMBLED_HTML_SAFETY_LIMIT_CHARS,
    MODEL_HTML_HARD_LIMIT_CHARS,
)

TARGET_LIMIT_CHARS = 36000


def check_length(html: str, *, scope: str = "model") -> dict:
    length = len(html or "")
    errors = []
    warnings = []
    hard_limit = MODEL_HTML_HARD_LIMIT_CHARS if scope == "model" else ASSEMBLED_HTML_SAFETY_LIMIT_CHARS
    if length > hard_limit:
        errors.append(
            {
                "type": "html_length_hard_limit" if scope == "model" else "assembled_html_safety_limit",
                "message": f"{'模型业务' if scope == 'model' else '最终装配'} HTML 长度 {length} 超过上限 {hard_limit}",
                "line": None,
            }
        )
    elif scope == "model" and length > TARGET_LIMIT_CHARS:
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
        "summary": f"{scope} HTML 长度检查完成",
        "errors": errors,
        "warnings": warnings,
    }
