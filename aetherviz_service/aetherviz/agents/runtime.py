"""Phase dispatcher for AetherViz workflows."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any

from langsmith import traceable

from aetherviz_service.aetherviz.api.sse import (
    agent_error_event,
    register_langsmith_trace_id,
    unregister_langsmith_trace_id,
)
from aetherviz_service.aetherviz.workflow.edit_html_workflow import run_edit_html_workflow
from aetherviz_service.aetherviz.workflow.generate_workflow import run_generate_workflow
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.aetherviz.workflow.plan_workflow import run_approve_plan_workflow, run_plan_workflow
from aetherviz_service.aetherviz.workflow.revise_plan_workflow import run_revise_plan_workflow
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)


def agent_runtime_stream(
    *,
    phase: str,
    topic: str = "",
    current_plan: dict[str, Any] | None = None,
    message: str | None = None,
    plan: dict[str, Any] | None = None,
    approved_plan: dict[str, Any] | None = None,
    current_html: str | None = None,
    context: dict[str, Any] | None = None,
) -> Iterator[str]:
    tracing_enabled = settings.langsmith_tracing and bool((settings.langsmith_api_key or "").strip())
    if not tracing_enabled:
        yield from _agent_runtime_stream_impl(
            phase=phase,
            topic=topic,
            current_plan=current_plan,
            message=message,
            plan=plan,
            approved_plan=approved_plan,
            current_html=current_html,
            context=context,
            langsmith_trace_id=None,
        )
        return

    trace_id = uuid.uuid4()
    yield from _traced_agent_runtime_stream(
        phase=phase,
        topic=topic,
        current_plan=current_plan,
        message=message,
        plan=plan,
        approved_plan=approved_plan,
        current_html=current_html,
        context=context,
        langsmith_trace_id=str(trace_id),
        langsmith_extra={
            "run_id": trace_id,
            "metadata": {"component": "aetherviz", "phase": phase},
        },
    )


@traceable(
    name="aetherviz.request",
    run_type="chain",
    metadata={"component": "aetherviz"},
    process_inputs=lambda inputs: {"phase": inputs.get("phase"), "topic": inputs.get("topic")},
    reduce_fn=lambda chunks: _summarize_runtime_sse(chunks),
)
def _traced_agent_runtime_stream(**kwargs: Any) -> Iterator[str]:
    yield from _agent_runtime_stream_impl(**kwargs)


def _agent_runtime_stream_impl(
    *,
    phase: str,
    topic: str = "",
    current_plan: dict[str, Any] | None = None,
    message: str | None = None,
    plan: dict[str, Any] | None = None,
    approved_plan: dict[str, Any] | None = None,
    current_html: str | None = None,
    context: dict[str, Any] | None = None,
    langsmith_trace_id: str | None = None,
) -> Iterator[str]:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    register_langsmith_trace_id(run_id, langsmith_trace_id)
    try:
        if phase == "plan":
            yield from run_plan_workflow(run_id=run_id, topic=topic, context=context)
            return
        if phase == "revise_plan":
            yield from run_revise_plan_workflow(
                run_id=run_id,
                topic=topic,
                current_plan=current_plan or {},
                message=message or "",
                context=context,
            )
            return
        if phase == "approve_plan":
            yield from run_approve_plan_workflow(run_id=run_id, plan=plan or {})
            return
        if phase == "generate":
            generation_topic = topic or str((approved_plan or {}).get("title") or "AI教学动画")
            normalized_plan = normalize_plan(approved_plan, generation_topic)
            yield from run_generate_workflow(
                run_id=run_id,
                topic=generation_topic,
                approved_plan=normalized_plan,
            )
            return
        if phase == "edit_html":
            yield from run_edit_html_workflow(
                run_id=run_id,
                current_html=current_html or "",
                message=message or "",
                context=context,
            )
            return
        yield agent_error_event(run_id=run_id, phase=phase, code="invalid_phase", message=f"不支持的 phase：{phase}")
    except Exception as exc:
        logger.exception("AetherViz runtime failed")
        yield agent_error_event(
            run_id=run_id,
            phase=phase,
            code="runtime_error",
            message="生成工作流执行失败",
            detail=str(exc),
        )
    finally:
        unregister_langsmith_trace_id(run_id)


def _summarize_runtime_sse(chunks: list[str]) -> dict[str, Any]:
    events: list[str] = []
    error_code: str | None = None
    for chunk in chunks:
        event = next((line[7:] for line in chunk.splitlines() if line.startswith("event: ")), "")
        if event:
            events.append(event)
        if event != "error":
            continue
        data_line = next((line[6:] for line in chunk.splitlines() if line.startswith("data: ")), "")
        if not data_line:
            continue
        try:
            payload = json.loads(data_line)
        except ValueError:
            continue
        error_code = str((payload.get("data") or {}).get("code") or "") or None
    return {
        "sse_event_count": len(events),
        "outcome": "error" if "error" in events else "success",
        "completed": "error" not in events,
        "error_code": error_code,
    }
