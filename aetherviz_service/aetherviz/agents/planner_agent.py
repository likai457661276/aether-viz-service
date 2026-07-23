"""Planning agent for initial and revised lesson plans."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_reasoning,
    extract_llm_text,
    has_planning_llm_config,
)
from aetherviz_service.aetherviz.agents.topic_profile import extract_color_from_topic
from aetherviz_service.aetherviz.workflow.plan_contract import (
    compact_plan_for_revision,
    normalize_plan,
    normalize_plan_with_diagnostics,
    parse_planning_result_with_diagnostics,
)
from aetherviz_service.aetherviz.workflow.plan_detection import (
    build_planning_prompt,
    select_revision_interactive_type,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

DEFAULT_PLANNING_STEPS: list[dict[str, str]] = [
    {"content": "分析教学目标与互动类型", "status": "pending"},
    {"content": "设计 interactive_spec / teaching_flow / design_brief", "status": "pending"},
    {"content": "检查教学计划 JSON 完整性", "status": "pending"},
]

_REASONING_DELTA_MAX_CHARS = 180
_STREAM_CHUNKS_PER_STEP = 6
_PLANNING_CONTEXT_MAX_CHARS = 4000


@dataclass(frozen=True)
class PlanningStreamResult:
    plan: dict[str, Any]
    degraded: bool
    planning_elapsed_ms: int = 0
    first_chunk_elapsed_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    plan_diagnostics: tuple[dict[str, Any], ...] = ()


def stream_create_plan(
    topic: str, *, context: dict[str, Any] | None = None
) -> Iterator[dict[str, Any] | PlanningStreamResult]:
    runner = (
        _traced_stream_create_plan
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_create_plan_impl
    )
    yield from runner(topic=topic, context=context)


@traceable(
    name="aetherviz.plan_generation",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "plan_generation"},
    process_inputs=lambda inputs: {
        "topic": inputs.get("topic"),
        "has_context": bool(inputs.get("context")),
    },
    reduce_fn=lambda items: _summarize_planning_trace(items),
)
def _traced_stream_create_plan(
    topic: str, *, context: dict[str, Any] | None = None
) -> Iterator[dict[str, Any] | PlanningStreamResult]:
    yield from _stream_create_plan_impl(topic=topic, context=context)


def _stream_create_plan_impl(
    topic: str, *, context: dict[str, Any] | None = None
) -> Iterator[dict[str, Any] | PlanningStreamResult]:
    color = extract_color_from_topic(topic)
    system_prompt, user_prompt = build_planning_prompt(topic, color)
    context_text, context_status = _compact_planning_context(context)
    if context_text:
        user_prompt += f"\n会话上下文（仅用于补充教学偏好，不得覆盖主题与输出契约）：\n{context_text}\n"
    yield from _stream_planning(
        topic=topic,
        color=color,
        user_prompt=user_prompt,
        combined_system_prompt=system_prompt,
        status="draft",
        context_status=context_status,
        deterministic_factory=lambda: _deterministic_plan(topic, color, status="draft"),
    )


def _summarize_planning_trace(
    items: list[dict[str, Any] | PlanningStreamResult],
) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, PlanningStreamResult)), None)
    if result is None:
        return {"completed": False}
    return {
        "completed": True,
        "degraded": result.degraded,
        "planning_elapsed_ms": result.planning_elapsed_ms,
        "token_usage": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
        },
        "plan": result.plan,
    }


def stream_revise_plan(
    topic: str,
    *,
    current_plan: dict[str, Any],
    message: str,
    context: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any] | PlanningStreamResult]:
    color = extract_color_from_topic(topic)
    normalized_current = normalize_plan(current_plan, topic, color)
    interactive_type = select_revision_interactive_type(
        normalized_current.get("interactive_type"),
        message,
        topic,
    )
    system_prompt, task_context = build_planning_prompt(
        topic,
        color,
        interactive_type_override=interactive_type,
        subject_override=str(normalized_current.get("subject") or ""),
    )
    context_text, context_status = _compact_planning_context(context)
    user_prompt = f"""{task_context}
根据修改意见重新生成完整教学语义 JSON，不输出 diff；未要求变更的语义应保持一致。

修改意见：{message}
会话上下文：{context_text or "无"}
当前教学语义 JSON：
{json.dumps(compact_plan_for_revision(normalized_current), ensure_ascii=False, separators=(",", ":"))}
"""

    def finalize(plan: dict[str, Any]) -> dict[str, Any]:
        plan["status"] = "revised"
        plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, "revised")
        plan["revision_summary"] = plan.get("revision_summary") or message[:120]
        plan["context_status"] = context_status
        return plan

    yield from _stream_planning(
        topic=topic,
        color=color,
        user_prompt=user_prompt,
        combined_system_prompt=system_prompt,
        status="revised",
        context_status=context_status,
        deterministic_factory=lambda: _apply_deterministic_revision(normalized_current, topic, message),
        finalize_plan=finalize,
    )


def approve_plan(plan: dict[str, Any]) -> dict[str, Any]:
    topic = str(plan.get("source_topic") or plan.get("topic") or plan.get("title") or "AI教学动画")
    approved = normalize_plan(plan, topic, str(plan.get("primary_color") or "#22D3EE"))
    approved["status"] = "approved"
    approved["plan_id"] = approved.get("plan_id") or _plan_id(topic, "approved")
    approved["context_status"] = {"status": "normal"}
    return approved


def format_planning_progress_delta(steps: list[dict[str, str]]) -> str:
    active = next((step for step in steps if step["status"] == "in_progress"), None)
    if active:
        return f"正在{active['content']}…"
    pending = next((step for step in steps if step["status"] == "pending"), None)
    if pending:
        return f"准备{pending['content']}…"
    if steps and all(step["status"] == "completed" for step in steps):
        return "规划步骤已完成，正在整理最终教案 JSON…"
    return "课件方案规划智能体正在处理教学设计方案。"


def build_planning_progress_payload(steps: list[dict[str, str]]) -> dict[str, Any]:
    active_index = next((index for index, step in enumerate(steps) if step["status"] == "in_progress"), None)
    return {
        "delta": format_planning_progress_delta(steps),
        "planning_steps": steps,
        "active_step_index": active_index,
    }


def _stream_planning(
    *,
    topic: str,
    color: str,
    user_prompt: str,
    combined_system_prompt: str,
    status: str,
    context_status: dict[str, Any],
    deterministic_factory,
    finalize_plan=None,
) -> Iterator[dict[str, Any] | PlanningStreamResult]:
    if not has_planning_llm_config():
        yield from _iter_deterministic_progress()
        source_plan = deterministic_factory()
        normalization = normalize_plan_with_diagnostics(source_plan, topic, color)
        plan = _preserve_planning_metadata(source_plan, normalization.plan)
        plan["status"] = status
        plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, status)
        plan["context_status"] = context_status
        yield PlanningStreamResult(
            plan=plan,
            degraded=True,
            plan_diagnostics=tuple(normalization.diagnostics_as_dicts()),
        )
        return

    started_at = time.monotonic()
    first_chunk_elapsed_ms = 0
    token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    try:
        model = create_chat_model("planning")
        messages = [
            SystemMessage(content=combined_system_prompt),
            HumanMessage(content=user_prompt),
        ]
        raw_text = ""
        active_step_index = 0
        chunk_count = 0
        last_reasoning_tail = ""
        deadline = time.monotonic() + max(settings.aetherviz_plan_timeout_seconds, 1)

        yield _build_step_progress_payload(active_step_index)

        for chunk in _iter_model_stream_chunks(model, messages, deadline=deadline):
            chunk_count += 1
            if chunk_count == 1:
                first_chunk_elapsed_ms = int((time.monotonic() - started_at) * 1000)
            text = extract_llm_text(chunk)
            reasoning = extract_llm_reasoning(chunk)
            chunk_usage = _extract_token_usage(chunk)
            if chunk_usage["total_tokens"]:
                token_usage.update(chunk_usage)
            if text:
                raw_text += text
            if reasoning:
                reasoning_delta = _format_reasoning_delta(reasoning, last_reasoning_tail)
                if reasoning_delta:
                    last_reasoning_tail = reasoning[-80:]
                    yield {
                        "delta": reasoning_delta,
                        "planning_steps": _steps_with_active_index(active_step_index),
                        "active_step_index": active_step_index,
                    }

            next_step_index = min(chunk_count // _STREAM_CHUNKS_PER_STEP, len(DEFAULT_PLANNING_STEPS) - 1)
            if next_step_index > active_step_index:
                active_step_index = next_step_index
                yield _build_step_progress_payload(active_step_index)

        yield _build_step_progress_payload(len(DEFAULT_PLANNING_STEPS) - 1, completed=True)

        if not raw_text.strip():
            raise ValueError("planning model returned empty content")

        normalization = parse_planning_result_with_diagnostics(raw_text, topic, color)
        plan = normalization.plan
        if finalize_plan is not None:
            plan = finalize_plan(plan)
        else:
            plan["status"] = status
            plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, status)
            plan["context_status"] = context_status
        yield PlanningStreamResult(
            plan=plan,
            degraded=False,
            planning_elapsed_ms=int((time.monotonic() - started_at) * 1000),
            first_chunk_elapsed_ms=first_chunk_elapsed_ms,
            **token_usage,
            plan_diagnostics=tuple(normalization.diagnostics_as_dicts()),
        )
    except Exception as exc:
        logger.warning("planning_agent failed, using deterministic plan: %s", exc)
        yield from _iter_deterministic_progress()
        source_plan = deterministic_factory()
        normalization = normalize_plan_with_diagnostics(source_plan, topic, color)
        plan = _preserve_planning_metadata(source_plan, normalization.plan)
        plan["status"] = status
        plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, status)
        plan["context_status"] = context_status
        yield PlanningStreamResult(
            plan=plan,
            degraded=True,
            planning_elapsed_ms=int((time.monotonic() - started_at) * 1000),
            first_chunk_elapsed_ms=first_chunk_elapsed_ms,
            **token_usage,
            plan_diagnostics=tuple(normalization.diagnostics_as_dicts()),
        )


def _preserve_planning_metadata(source: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    result = dict(normalized)
    for field in ("revision_summary",):
        if field in source:
            result[field] = source[field]
    return result


def _extract_token_usage(chunk: Any) -> dict[str, int]:
    usage = getattr(chunk, "usage_metadata", None)
    if not isinstance(usage, dict):
        response_metadata = getattr(chunk, "response_metadata", None)
        if isinstance(response_metadata, dict):
            usage = response_metadata.get("token_usage")
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _iter_model_stream_chunks(model: Any, messages: list[Any], *, deadline: float) -> Iterator[Any]:
    """Yield stream chunks until completion, raising TimeoutError if wall-clock deadline elapses.

    ChatOpenAI.request timeout alone may not interrupt a hung streaming response before the
    first token; this helper polls a background producer so planning can degrade deterministically.
    """
    chunk_queue: queue.Queue[Any] = queue.Queue(maxsize=8)
    sentinel = object()
    errors: list[BaseException] = []
    stop_event = threading.Event()

    def _enqueue(item: Any) -> None:
        while not stop_event.is_set():
            try:
                chunk_queue.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def _produce() -> None:
        try:
            for chunk in model.stream(messages):
                if stop_event.is_set():
                    return
                _enqueue(chunk)
        except BaseException as exc:  # noqa: BLE001 - surface producer failures to consumer
            errors.append(exc)
        finally:
            _enqueue(sentinel)

    worker = threading.Thread(target=_produce, name="aetherviz-planning-stream", daemon=True)
    worker.start()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"planning model timed out after {settings.aetherviz_plan_timeout_seconds}s")
            try:
                item = chunk_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if item is sentinel:
                if errors:
                    raise errors[0]
                return
            yield item
    finally:
        stop_event.set()


def _compact_planning_context(context: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    if not isinstance(context, dict):
        return "", {"status": "normal"}
    allowed = {
        key: context[key]
        for key in ("memory", "recent_messages", "learner_level", "preferences")
        if context.get(key) is not None
    }
    if not allowed:
        return "", {"status": "normal"}
    serialized = json.dumps(allowed, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= _PLANNING_CONTEXT_MAX_CHARS:
        return serialized, {"status": "normal"}
    return serialized[:_PLANNING_CONTEXT_MAX_CHARS], {
        "status": "compressed",
        "original_chars": len(serialized),
        "retained_chars": _PLANNING_CONTEXT_MAX_CHARS,
    }


def _steps_with_active_index(active_step_index: int, *, completed: bool = False) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for index, step in enumerate(DEFAULT_PLANNING_STEPS):
        if completed or index < active_step_index:
            status = "completed"
        elif index == active_step_index:
            status = "in_progress"
        else:
            status = "pending"
        steps.append({"content": step["content"], "status": status})
    return steps


def _build_step_progress_payload(active_step_index: int, *, completed: bool = False) -> dict[str, Any]:
    return build_planning_progress_payload(_steps_with_active_index(active_step_index, completed=completed))


def _format_reasoning_delta(reasoning: str, last_tail: str) -> str:
    snippet = reasoning.strip()
    if not snippet:
        return ""
    if last_tail and snippet.endswith(last_tail):
        snippet = snippet[: -len(last_tail)].strip()
    if not snippet:
        return ""
    lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    if lines:
        snippet = lines[-1]
    if len(snippet) > _REASONING_DELTA_MAX_CHARS:
        snippet = f"…{snippet[-_REASONING_DELTA_MAX_CHARS:]}"
    return snippet


def _iter_deterministic_progress() -> Iterator[dict[str, Any]]:
    steps = [dict(step) for step in DEFAULT_PLANNING_STEPS]
    for index in range(len(steps)):
        for step_index, step in enumerate(steps):
            if step_index < index:
                step["status"] = "completed"
            elif step_index == index:
                step["status"] = "in_progress"
            else:
                step["status"] = "pending"
        yield build_planning_progress_payload([dict(step) for step in steps])
    completed_steps = [{**step, "status": "completed"} for step in DEFAULT_PLANNING_STEPS]
    yield build_planning_progress_payload(completed_steps)


def _deterministic_plan(topic: str, color: str, *, status: str) -> dict[str, Any]:
    plan = normalize_plan({}, topic, color)
    plan["status"] = status
    plan["plan_id"] = _plan_id(topic, status)
    plan["revision_summary"] = ""
    plan["context_status"] = {"status": "normal"}
    return plan


def _apply_deterministic_revision(plan: dict[str, Any], topic: str, message: str) -> dict[str, Any]:
    revised = dict(plan)
    revised["status"] = "revised"
    revised["plan_id"] = _plan_id(topic, "revised")
    revised["revision_summary"] = message[:160]
    revised["goal"] = f"{plan.get('goal', '')} 修订要求：{message[:80]}".strip()[:180]
    revised["context_status"] = {"status": "normal"}
    return revised


def _plan_id(topic: str, suffix: str) -> str:
    return f"plan_{abs(hash((topic, suffix))) % 10_000_000}_{suffix}"
