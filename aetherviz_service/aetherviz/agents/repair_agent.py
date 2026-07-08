"""HTML repair agent."""

from __future__ import annotations

import json
import logging
from typing import Any

from aetherviz_service.aetherviz.agents.model_factory import create_agent_app, extract_agent_text, has_primary_llm_config
from aetherviz_service.aetherviz.agents.instructions import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html

logger = logging.getLogger(__name__)


def repair_html(
    *,
    topic: str,
    plan: dict[str, Any],
    raw_html: str,
    report: dict[str, Any],
    original_prompt: str = "",
) -> tuple[str, bool]:
    if not has_primary_llm_config():
        return _deterministic_repair(raw_html), True
    try:
        prompt = build_repair_prompt(
            topic=topic,
            plan=plan,
            original_prompt=original_prompt,
            raw_html=raw_html,
            error_detail=json.dumps(report, ensure_ascii=False),
            source_label="Deep Agents 检查",
        )
        agent = create_agent_app("repair", system_prompt=REPAIR_SYSTEM_PROMPT)
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        return sanitize_aetherviz_html(parse_interactive_html(extract_agent_text(result))), False
    except Exception as exc:
        logger.warning("repair_agent failed, using deterministic repair: %s", exc)
        return _deterministic_repair(raw_html), True


def _deterministic_repair(html: str) -> str:
    repaired = html.strip()
    if not repaired.lower().startswith("<!doctype html>"):
        repaired = "<!DOCTYPE html>\n" + repaired
    if "</html>" not in repaired.lower():
        repaired += "\n</html>"
    return repaired
