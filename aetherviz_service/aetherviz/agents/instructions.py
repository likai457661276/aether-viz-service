"""Compatibility re-exports for edit and bounded repair prompts."""

from aetherviz_service.aetherviz.contracts.repair.prompts import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from aetherviz_service.aetherviz.edit.prompts import EDIT_HTML_SYSTEM_PROMPT, build_edit_html_prompt

__all__ = [
    "EDIT_HTML_SYSTEM_PROMPT",
    "REPAIR_SYSTEM_PROMPT",
    "build_edit_html_prompt",
    "build_repair_prompt",
]
