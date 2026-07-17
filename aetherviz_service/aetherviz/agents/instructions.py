"""Compatibility re-exports. Prefer generate.prompts / edit.prompts / contracts.repair.prompts."""

from aetherviz_service.aetherviz.contracts.repair.prompts import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from aetherviz_service.aetherviz.edit.prompts import EDIT_HTML_SYSTEM_PROMPT, build_edit_html_prompt
from aetherviz_service.aetherviz.generate.prompts import (
    DIAGRAM_SYSTEM_PROMPT,
    GAME_SYSTEM_PROMPT,
    GRAPHICS_CRAFT_PROMPT,
    INTERACTIVE_HTML_SYSTEM_PROMPT,
    NUMERIC_PRESENTATION_PROMPT,
    SERVER_LAYOUT_CONTRACT_PROMPT,
    SIMULATION_SYSTEM_PROMPT,
    STAGE_CENTERING_AND_LABEL_PROMPT,
    VISUAL_DESIGN_SYSTEM_PROMPT,
    WIDGET_CORE_PROMPT,
    build_interactive_generation_prompt,
    system_prompt_for_interactive_type,
)

__all__ = [
    "DIAGRAM_SYSTEM_PROMPT",
    "EDIT_HTML_SYSTEM_PROMPT",
    "GAME_SYSTEM_PROMPT",
    "GRAPHICS_CRAFT_PROMPT",
    "INTERACTIVE_HTML_SYSTEM_PROMPT",
    "NUMERIC_PRESENTATION_PROMPT",
    "REPAIR_SYSTEM_PROMPT",
    "SERVER_LAYOUT_CONTRACT_PROMPT",
    "SIMULATION_SYSTEM_PROMPT",
    "STAGE_CENTERING_AND_LABEL_PROMPT",
    "VISUAL_DESIGN_SYSTEM_PROMPT",
    "WIDGET_CORE_PROMPT",
    "build_edit_html_prompt",
    "build_interactive_generation_prompt",
    "build_repair_prompt",
    "system_prompt_for_interactive_type",
]
