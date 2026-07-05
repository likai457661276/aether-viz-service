"""Parse, sanitize and validate generated AetherViz HTML."""

from __future__ import annotations

import logging

from aetherviz_service.aetherviz.fallback_validator import parse_interactive_html
from aetherviz_service.aetherviz.validator import sanitize_aetherviz_html, validate_aetherviz_html

logger = logging.getLogger(__name__)


def parse_and_validate_html(raw_html: str, topic: str, plan: dict) -> tuple[str, list[str]]:
    logger.info("LLM AetherViz SVG 响应长度 %s", len(raw_html))
    html_output = parse_interactive_html(raw_html)
    cleaned_html = sanitize_aetherviz_html(html_output)
    warnings = validate_aetherviz_html(
        cleaned_html,
        topic=topic,
        strict=False,
    )
    return cleaned_html, warnings
