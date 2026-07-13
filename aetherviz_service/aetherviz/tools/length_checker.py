"""HTML length checker."""

from __future__ import annotations

import re

from aetherviz_service.aetherviz.constants import (
    ASSEMBLED_HTML_SAFETY_LIMIT_CHARS,
    MODEL_HTML_HARD_LIMIT_CHARS,
)

TARGET_LIMIT_CHARS = 36000
_SERVICE_OWNED_TAG_RE = re.compile(
    r"<(script|style)\b(?=[^>]*\bdata-aetherviz-(?:"
    r"layout-contract|layout-guard|control-contract|animation-contract|"
    r"scale-guard|message-bridge|ready-guard)\b)[^>]*>[\s\S]*?</\1\s*>",
    re.IGNORECASE,
)


def check_length(html: str, *, scope: str = "model") -> dict:
    source = html or ""
    # Deterministic service contracts are assembly/repair overhead, not model
    # authored business code. Excluding only explicitly marked service tags
    # keeps a near-limit valid model output from becoming invalid after a guard
    # is injected, while the assembled safety limit still covers total size.
    measured = _SERVICE_OWNED_TAG_RE.sub("", source) if scope == "model" else source
    length = len(measured)
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
