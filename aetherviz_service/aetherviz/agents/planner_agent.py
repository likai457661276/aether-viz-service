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

from aetherviz_service.aetherviz.agents.model_factory import (
    create_chat_model,
    extract_llm_reasoning,
    extract_llm_text,
    has_planning_llm_config,
)
from aetherviz_service.aetherviz.agents.topic_profile import extract_color_from_topic
from aetherviz_service.aetherviz.workflow.plan_contract import (
    build_planning_prompt,
    compact_plan_for_revision,
    normalize_plan,
    parse_planning_result,
    select_revision_interactive_type,
)
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

DEFAULT_PLANNING_STEPS: list[dict[str, str]] = [
    {"content": "分析教学目标与互动类型", "status": "pending"},
    {"content": "设计 interactive_spec / teaching_flow / design_brief", "status": "pending"},
    {"content": "检查 JSON 字段完整性与约束", "status": "pending"},
]

_VALID_STEP_STATUS = {"pending", "in_progress", "completed"}
_REASONING_DELTA_MAX_CHARS = 180
_STREAM_CHUNKS_PER_STEP = 6


@dataclass(frozen=True)
class PlanningStreamResult:
    plan: dict[str, Any]
    degraded: bool
    planning_elapsed_ms: int = 0
    first_chunk_elapsed_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def stream_create_plan(topic: str, *, context: dict[str, Any] | None = None) -> Iterator[dict[str, Any] | PlanningStreamResult]:
    color = extract_color_from_topic(topic)
    system_prompt, user_prompt = build_planning_prompt(topic, color)
    yield from _stream_planning(
        topic=topic,
        color=color,
        user_prompt=user_prompt,
        combined_system_prompt=system_prompt,
        status="draft",
        deterministic_factory=lambda: _deterministic_plan(topic, color, status="draft"),
    )


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
    user_prompt = f"""{task_context}
根据修改意见重新生成完整教学语义 JSON，不输出 diff；未要求变更的语义应保持一致。

修改意见：{message}
当前教学语义 JSON：
{json.dumps(compact_plan_for_revision(normalized_current), ensure_ascii=False, separators=(",", ":"))}
"""

    def finalize(plan: dict[str, Any]) -> dict[str, Any]:
        plan["status"] = "revised"
        plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, "revised")
        plan["revision_summary"] = plan.get("revision_summary") or message[:120]
        plan["context_status"] = {"status": "normal"}
        return plan

    yield from _stream_planning(
        topic=topic,
        color=color,
        user_prompt=user_prompt,
        combined_system_prompt=system_prompt,
        status="revised",
        deterministic_factory=lambda: _apply_deterministic_revision(normalized_current, topic, message),
        finalize_plan=finalize,
    )


def create_plan(topic: str, *, context: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    result: PlanningStreamResult | None = None
    for item in stream_create_plan(topic, context=context):
        if isinstance(item, PlanningStreamResult):
            result = item
    if result is None:
        color = extract_color_from_topic(topic)
        return _deterministic_plan(topic, color, status="draft"), True
    return result.plan, result.degraded


def revise_plan(
    topic: str,
    *,
    current_plan: dict[str, Any],
    message: str,
    context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    result: PlanningStreamResult | None = None
    for item in stream_revise_plan(topic, current_plan=current_plan, message=message, context=context):
        if isinstance(item, PlanningStreamResult):
            result = item
    if result is None:
        color = extract_color_from_topic(topic)
        plan = normalize_plan(current_plan, topic, color)
        return _apply_deterministic_revision(plan, topic, message), True
    return result.plan, result.degraded


def approve_plan(plan: dict[str, Any]) -> dict[str, Any]:
    topic = str(plan.get("topic") or plan.get("title") or "AI互动实验")
    approved = normalize_plan(plan, topic, str(plan.get("primary_color") or "#22D3EE"))
    approved["status"] = "approved"
    approved["plan_id"] = approved.get("plan_id") or _plan_id(topic, "approved")
    approved["context_status"] = {"status": "normal"}
    return approved


def normalize_planning_steps(todos: list[Any]) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for item in todos:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("task") or "").strip()
        if not content:
            continue
        status = str(item.get("status") or "pending")
        if status not in _VALID_STEP_STATUS:
            status = "pending"
        steps.append({"content": content, "status": status})
    return steps


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


def extract_todos_from_stream_chunk(chunk: Any) -> list[Any] | None:
    if not isinstance(chunk, dict):
        return None
    if isinstance(chunk.get("todos"), list):
        return chunk["todos"]
    for node_update in chunk.values():
        if isinstance(node_update, dict) and isinstance(node_update.get("todos"), list):
            return node_update["todos"]
    return None


def _stream_planning(
    *,
    topic: str,
    color: str,
    user_prompt: str,
    combined_system_prompt: str,
    status: str,
    deterministic_factory,
    finalize_plan=None,
) -> Iterator[dict[str, Any] | PlanningStreamResult]:
    if not has_planning_llm_config():
        yield from _iter_deterministic_progress()
        plan = deterministic_factory()
        plan["status"] = status
        plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, status)
        plan["context_status"] = plan.get("context_status") or {"status": "compressed" if status == "revised" else "normal"}
        yield PlanningStreamResult(plan=plan, degraded=True)
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

        plan = parse_planning_result(raw_text, topic, color)
        if finalize_plan is not None:
            plan = finalize_plan(plan)
        else:
            plan["status"] = status
            plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, status)
            plan["context_status"] = {"status": "normal"}
        yield PlanningStreamResult(
            plan=plan,
            degraded=False,
            planning_elapsed_ms=int((time.monotonic() - started_at) * 1000),
            first_chunk_elapsed_ms=first_chunk_elapsed_ms,
            **token_usage,
        )
    except Exception as exc:
        logger.warning("planning_agent failed, using deterministic plan: %s", exc)
        yield from _iter_deterministic_progress()
        plan = deterministic_factory()
        plan["status"] = status
        plan["plan_id"] = plan.get("plan_id") or _plan_id(topic, status)
        plan["context_status"] = {"status": "compressed" if status == "revised" else "normal"}
        yield PlanningStreamResult(
            plan=plan,
            degraded=True,
            planning_elapsed_ms=int((time.monotonic() - started_at) * 1000),
            first_chunk_elapsed_ms=first_chunk_elapsed_ms,
            **token_usage,
        )


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
    chunk_queue: queue.Queue[Any] = queue.Queue()
    sentinel = object()
    errors: list[BaseException] = []

    def _produce() -> None:
        try:
            for chunk in model.stream(messages):
                chunk_queue.put(chunk)
        except BaseException as exc:  # noqa: BLE001 - surface producer failures to consumer
            errors.append(exc)
        finally:
            chunk_queue.put(sentinel)

    worker = threading.Thread(target=_produce, name="aetherviz-planning-stream", daemon=True)
    worker.start()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"planning model timed out after {settings.aetherviz_plan_timeout_seconds}s"
            )
        try:
            item = chunk_queue.get(timeout=min(remaining, 0.5))
        except queue.Empty:
            continue
        if item is sentinel:
            if errors:
                raise errors[0]
            return
        yield item


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
    revised["goal"] = f'{plan.get("goal", "")} 修订要求：{message[:80]}'.strip()[:180]
    revised["context_status"] = {"status": "compressed"}
    return revised


def _plan_id(topic: str, suffix: str) -> str:
    return f"plan_{abs(hash((topic, suffix))) % 10_000_000}_{suffix}"
