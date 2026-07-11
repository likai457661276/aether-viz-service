"""HTML edit workflow."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from aetherviz_service.aetherviz.agents.html_agent import (
    HTML_SIZE_EVENT_INTERVAL_BYTES,
    HtmlGenerationError,
    HtmlStreamResult,
    build_html_progress_payload,
    build_html_size_payload,
)
from aetherviz_service.aetherviz.agents.instructions import EDIT_HTML_SYSTEM_PROMPT, build_edit_html_prompt
from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_text,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.aetherviz.workflow.generate_workflow import _run_html_workflow
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

def run_edit_html_workflow(
    *,
    run_id: str,
    current_html: str,
    message: str,
    context: dict[str, Any] | None,
) -> Iterator[str]:
    topic = _topic_from_context(context)
    plan = normalize_plan((context or {}).get("plan_summary") if isinstance(context, dict) else None, topic)
    yield from _run_html_workflow(
        run_id=run_id,
        phase="edit_html",
        start_event="html.edit_started",
        topic=topic,
        plan=plan,
        html_stream_factory=lambda: _stream_edit_html(
            topic=topic,
            message=message,
            current_html=current_html,
            context=context,
        ),
    )


def _stream_edit_html(
    *,
    topic: str,
    message: str,
    current_html: str,
    context: dict[str, Any] | None,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        yield build_html_progress_payload(
            [
                {"content": "分析用户修改意见与当前 HTML", "status": "completed"},
                {"content": "必要时更新页面文件", "status": "completed"},
                {"content": "输出修改后的完整 HTML", "status": "completed"},
            ]
        )
        yield HtmlStreamResult(html=current_html, degraded=True)
        return

    prompt = build_edit_html_prompt(
        topic=topic,
        instruction=message,
        current_html=current_html,
        context=context,
    )
    raw_text = ""
    last_size_event_bytes = 0
    timed_out = False
    deadline = time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1)
    yield build_html_progress_payload(
        [
            {"content": "分析用户修改意见与当前 HTML", "status": "in_progress"},
            {"content": "输出修改后的完整 HTML", "status": "pending"},
        ]
    )
    try:
        model = create_chat_model("edit")
        messages = [SystemMessage(content=EDIT_HTML_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        output_started = False
        for chunk in model.stream(messages):
            if time.monotonic() > deadline:
                timed_out = True
                logger.warning(
                    "edit_html model timed out after %ss; using best available output",
                    settings.aetherviz_html_timeout_seconds,
                )
                break
            text = extract_llm_text(chunk)
            if text:
                raw_text += text
                current_bytes = len(raw_text.encode("utf-8"))
                if not output_started:
                    output_started = True
                    yield build_html_progress_payload(
                        [
                            {"content": "分析用户修改意见与当前 HTML", "status": "completed"},
                            {"content": "输出修改后的完整 HTML", "status": "in_progress"},
                        ],
                        html_content=raw_text,
                    )
                    last_size_event_bytes = current_bytes
                elif current_bytes - last_size_event_bytes >= HTML_SIZE_EVENT_INTERVAL_BYTES:
                    yield build_html_size_payload(raw_text)
                    last_size_event_bytes = current_bytes
        if not raw_text.strip():
            raise ValueError("edit model returned empty content")
        edited_html = sanitize_aetherviz_html(parse_interactive_html(raw_text))
        yield build_html_progress_payload(
            [
                {"content": "分析用户修改意见与当前 HTML", "status": "completed"},
                {"content": "输出修改后的完整 HTML", "status": "completed"},
            ],
            html_content=edited_html,
        )
        yield HtmlStreamResult(
            html=edited_html,
            degraded=timed_out,
            truncated="</html" not in raw_text.lower(),
        )
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("edit_html model failed: %s", exc)
        if raw_text.strip():
            try:
                yield HtmlStreamResult(
                    html=sanitize_aetherviz_html(parse_interactive_html(raw_text)),
                    degraded=True,
                    truncated="</html" not in raw_text.lower(),
                )
                return
            except Exception:
                logger.warning("edit_html partial output failed parsing")
        raise HtmlGenerationError(
            "HTML 修改失败，未获得可用页面",
            code="edit_failed",
            detail=str(exc),
        ) from exc


def _topic_from_context(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return "AI互动实验"
    return str(context.get("topic") or context.get("user_message") or "AI互动实验")
