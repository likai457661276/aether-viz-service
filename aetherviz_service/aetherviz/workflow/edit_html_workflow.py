"""HTML edit workflow."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.instructions import REPAIR_SYSTEM_PROMPT
from aetherviz_service.aetherviz.agents.model_factory import create_agent_app, extract_agent_text, has_primary_llm_config
from aetherviz_service.aetherviz.sandbox.artifacts import SandboxArtifacts
from aetherviz_service.aetherviz.sandbox.manager import SandboxManager
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.aetherviz.workflow.generate_workflow import _run_html_workflow
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan

logger = logging.getLogger(__name__)


def run_edit_html_workflow(
    *,
    run_id: str,
    current_html: str,
    message: str,
    context: dict[str, Any] | None,
    sandbox: SandboxManager,
    artifacts: SandboxArtifacts,
) -> Iterator[str]:
    topic = _topic_from_context(context)
    plan = normalize_plan((context or {}).get("plan_summary") if isinstance(context, dict) else None, topic)
    yield from _run_html_workflow(
        run_id=run_id,
        phase="edit_html",
        start_event="html.edit_started",
        topic=topic,
        plan=plan,
        sandbox=sandbox,
        artifacts=artifacts,
        html_factory=lambda: _edit_html(current_html=current_html, message=message, context=context),
    )


def _edit_html(*, current_html: str, message: str, context: dict[str, Any] | None) -> tuple[str, bool]:
    if not has_primary_llm_config():
        return current_html, True
    prompt = f"""请基于用户修改意见输出新的完整自包含 HTML。

用户修改意见：{message}
上下文摘要：{context or {}}

当前 HTML：
{current_html}

只输出完整 HTML，不输出解释。
"""
    try:
        agent = create_agent_app("repair", system_prompt=REPAIR_SYSTEM_PROMPT)
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        return sanitize_aetherviz_html(parse_interactive_html(extract_agent_text(result))), False
    except Exception as exc:
        logger.warning("edit_html agent failed, returning original html: %s", exc)
        return current_html, True


def _topic_from_context(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return "AI互动实验"
    return str(context.get("topic") or context.get("user_message") or "AI互动实验")
