"""HTML edit workflow."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.html_agent import (
    HtmlStreamResult,
    _extract_files_from_stream_chunk,
    _extract_ready_html_from_agent_state,
    _extract_ready_html_from_files,
    build_html_progress_payload,
)
from aetherviz_service.aetherviz.agents.instructions import EDIT_HTML_SYSTEM_PROMPT, build_edit_html_prompt
from aetherviz_service.aetherviz.agents.model_factory import (
    agent_invoke_config,
    create_agent_app,
    extract_agent_text,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.sandbox.artifacts import SandboxArtifacts
from aetherviz_service.aetherviz.sandbox.manager import SandboxManager
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.aetherviz.workflow.generate_workflow import _run_html_workflow
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

EDIT_HTML_WORKFLOW_PROMPT = """你是 edit_html_agent，负责编辑现有 HTML。

工作方式（必须遵守）：
1. 基于用户修改意见直接 write_file 或 edit_file 更新 /widget.html（edit_file 最多 3 次）。
2. 修改完成后，立即在最终回复直接输出完整 <!DOCTYPE html>...</html> 并结束任务。
3. 禁止使用 write_todos、execute、task 子代理；禁止 read_file 分页回读后循环打磨。
4. 最终回复必须是完整 HTML 文档，禁止 Markdown 包装。"""


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
    combined_system_prompt = f"{EDIT_HTML_WORKFLOW_PROMPT}\n\n{EDIT_HTML_SYSTEM_PROMPT}"
    final_state: dict[str, Any] | None = None
    timed_out = False
    deadline = time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1)
    yield build_html_progress_payload(
        [
            {"content": "分析用户修改意见与当前 HTML", "status": "in_progress"},
            {"content": "输出修改后的完整 HTML", "status": "pending"},
        ]
    )
    try:
        agent = create_agent_app("repair", system_prompt=combined_system_prompt)
        for mode, chunk in agent.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            stream_mode=["updates", "values"],
            config=agent_invoke_config("repair"),
        ):
            if time.monotonic() > deadline:
                timed_out = True
                logger.warning(
                    "edit_html agent timed out after %ss; using best available Deep Agents output",
                    settings.aetherviz_html_timeout_seconds,
                )
                break
            if mode == "values" and isinstance(chunk, dict):
                final_state = chunk
                ready_html = _extract_ready_html_from_agent_state(chunk)
                if ready_html:
                    yield build_html_progress_payload(
                        [
                            {"content": "分析用户修改意见与当前 HTML", "status": "completed"},
                            {"content": "输出修改后的完整 HTML", "status": "completed"},
                        ]
                    )
                    yield HtmlStreamResult(
                        html=sanitize_aetherviz_html(parse_interactive_html(ready_html)),
                        degraded=timed_out,
                    )
                    return
            elif mode == "updates" and isinstance(chunk, dict):
                files = _extract_files_from_stream_chunk(chunk)
                if files:
                    ready_html = _extract_ready_html_from_files(files)
                    if ready_html:
                        final_state = {"files": files, **(final_state or {})}
                        yield build_html_progress_payload(
                            [
                                {"content": "分析用户修改意见与当前 HTML", "status": "completed"},
                                {"content": "输出修改后的完整 HTML", "status": "completed"},
                            ]
                        )
                        yield HtmlStreamResult(
                            html=sanitize_aetherviz_html(parse_interactive_html(ready_html)),
                            degraded=timed_out,
                        )
                        return
        raw_text = _extract_ready_html_from_agent_state(final_state or {}) or extract_agent_text(final_state or {})
        yield HtmlStreamResult(
            html=sanitize_aetherviz_html(parse_interactive_html(raw_text)),
            degraded=timed_out,
        )
    except Exception as exc:
        logger.warning("edit_html agent failed, returning original html: %s", exc)
        partial_html = _extract_ready_html_from_agent_state(final_state or {})
        if partial_html.strip():
            yield HtmlStreamResult(
                html=sanitize_aetherviz_html(parse_interactive_html(partial_html)),
                degraded=True,
            )
            return
        yield HtmlStreamResult(html=current_html, degraded=True)


def _edit_html(*, topic: str, message: str, current_html: str, context: dict[str, Any] | None) -> tuple[str, bool]:
    result: HtmlStreamResult | None = None
    for item in _stream_edit_html(topic=topic, message=message, current_html=current_html, context=context):
        if isinstance(item, HtmlStreamResult):
            result = item
    if result is None:
        return current_html, True
    return result.html, result.degraded


def _topic_from_context(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return "AI互动实验"
    return str(context.get("topic") or context.get("user_message") or "AI互动实验")
