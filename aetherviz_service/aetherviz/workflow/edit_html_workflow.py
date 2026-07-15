"""HTML edit workflow."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

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
    extract_llm_usage,
    has_primary_llm_config,
)
from aetherviz_service.aetherviz.limits import (
    FULL_HTML_OUTPUT_RESERVE_CHARS,
    estimated_output_capacity_chars,
)
from aetherviz_service.aetherviz.tools.html_output import parse_interactive_html, sanitize_aetherviz_html
from aetherviz_service.aetherviz.tools.layout_contract import extract_business_html
from aetherviz_service.aetherviz.workflow.generate_workflow import _run_html_workflow
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

_REQUIRED_WIDGET_ACTIONS = (
    "SET_WIDGET_STATE",
    "HIGHLIGHT_ELEMENT",
    "ANNOTATE_ELEMENT",
    "REVEAL_ELEMENT",
)


def run_edit_html_workflow(
    *,
    run_id: str,
    current_html: str,
    message: str,
    context: dict[str, Any] | None,
) -> Iterator[str]:
    tracing_enabled = settings.langsmith_tracing and bool((settings.langsmith_api_key or "").strip())
    runner = _traced_run_edit_html_workflow if tracing_enabled else _run_edit_html_workflow_impl
    if runner is _traced_run_edit_html_workflow:
        yield from runner(
            run_id=run_id,
            current_html=current_html,
            message=message,
            context=context,
            langsmith_extra={
                "metadata": {
                    "component": "aetherviz",
                    "phase": "edit_html",
                    "run_id": run_id,
                }
            },
        )
        return
    yield from runner(run_id=run_id, current_html=current_html, message=message, context=context)


@traceable(
    name="aetherviz.edit_workflow",
    run_type="chain",
    metadata={"component": "aetherviz", "phase": "edit_html"},
    process_inputs=lambda inputs: {
        "run_id": inputs.get("run_id"),
        "assembled_chars": len(inputs.get("current_html") or ""),
        "instruction_chars": len(inputs.get("message") or ""),
    },
    reduce_fn=lambda chunks: _summarize_edit_sse(chunks),
)
def _traced_run_edit_html_workflow(
    *,
    run_id: str,
    current_html: str,
    message: str,
    context: dict[str, Any] | None,
) -> Iterator[str]:
    yield from _run_edit_html_workflow_impl(
        run_id=run_id,
        current_html=current_html,
        message=message,
        context=context,
    )


def _run_edit_html_workflow_impl(
    *,
    run_id: str,
    current_html: str,
    message: str,
    context: dict[str, Any] | None,
) -> Iterator[str]:
    topic = _topic_from_context(context)
    plan = normalize_plan((context or {}).get("plan_summary") if isinstance(context, dict) else None, topic)
    business_html = extract_business_html(current_html)
    yield from _run_html_workflow(
        run_id=run_id,
        phase="edit_html",
        start_event="html.edit_started",
        topic=topic,
        plan=plan,
        html_stream_factory=lambda: _stream_edit_html(
            topic=topic,
            message=message,
            current_html=business_html,
        ),
    )


def _stream_edit_html(
    *,
    topic: str,
    message: str,
    current_html: str,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    runner = (
        _traced_stream_edit_html
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _stream_edit_html_impl
    )
    yield from runner(topic=topic, message=message, current_html=current_html)


@traceable(
    name="aetherviz.html_edit",
    run_type="chain",
    metadata={"component": "aetherviz", "stage": "html_edit"},
    process_inputs=lambda inputs: {
        "topic": inputs.get("topic"),
        "business_chars": len(inputs.get("current_html") or ""),
        "instruction_chars": len(inputs.get("message") or ""),
        "full_output_budget_chars": estimated_output_capacity_chars(settings.aetherviz_edit_max_tokens),
        "edit_strategy": "full_html_regeneration",
    },
    reduce_fn=lambda items: _summarize_edit_stream(items),
)
def _traced_stream_edit_html(
    *,
    topic: str,
    message: str,
    current_html: str,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    yield from _stream_edit_html_impl(
        topic=topic,
        message=message,
        current_html=current_html,
    )


def _stream_edit_html_impl(
    *,
    topic: str,
    message: str,
    current_html: str,
) -> Iterator[dict[str, Any] | HtmlStreamResult]:
    if not has_primary_llm_config():
        raise HtmlGenerationError(
            "HTML 修改失败，未配置可用的模型服务，原页面已保留",
            code="model_unavailable",
            detail="OPENAI_API_KEY is not configured",
        )

    if not _has_full_edit_budget(current_html):
        raise HtmlGenerationError(
            "HTML 修改失败，完整编辑输出预算不足，原页面已保留",
            code="edit_budget_exceeded",
            detail=f"business_chars={len(current_html)}",
        )

    prompt = build_edit_html_prompt(
        instruction=message,
        current_html=current_html,
    )
    raw_text = ""
    last_size_event_bytes = 0
    timed_out = False
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    deadline = time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1)
    yield build_html_progress_payload(
        [
            {"content": "分析当前 HTML 与修改意见", "status": "in_progress"},
            {"content": "重新生成完整 HTML", "status": "pending"},
        ]
    )
    try:
        model = create_chat_model("edit")
        messages = [SystemMessage(content=EDIT_HTML_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        output_started = False
        for chunk in model.stream(messages):
            chunk_input_tokens, chunk_output_tokens = extract_llm_usage(chunk)
            input_tokens = chunk_input_tokens or input_tokens
            output_tokens = chunk_output_tokens or output_tokens
            if time.monotonic() > deadline:
                timed_out = True
                logger.warning(
                    "edit_html model timed out after %ss; using best available output",
                    settings.aetherviz_html_timeout_seconds,
                )
                break
            text = extract_llm_text(chunk)
            response_metadata = getattr(chunk, "response_metadata", None)
            if isinstance(response_metadata, dict) and response_metadata.get("finish_reason"):
                finish_reason = str(response_metadata["finish_reason"])
            if text:
                raw_text += text
                current_bytes = len(raw_text.encode("utf-8"))
                if not output_started:
                    output_started = True
                    yield build_html_progress_payload(
                        [
                            {"content": "分析当前 HTML 与修改意见", "status": "completed"},
                            {"content": "重新生成完整 HTML", "status": "in_progress"},
                        ],
                        html_content=raw_text,
                    )
                    last_size_event_bytes = current_bytes
                elif current_bytes - last_size_event_bytes >= HTML_SIZE_EVENT_INTERVAL_BYTES:
                    yield build_html_size_payload(raw_text)
                    last_size_event_bytes = current_bytes
        if not raw_text.strip():
            raise ValueError("edit model returned empty content")
        truncated = "</html" not in raw_text.lower() or finish_reason in {"length", "max_tokens"}
        if truncated:
            raise HtmlGenerationError(
                "HTML 修改失败，模型输出被截断，原页面已保留",
                code="edit_truncated",
                detail=f"finish_reason={finish_reason or 'missing_html_end'}; chars={len(raw_text)}",
            )
        edited_html = sanitize_aetherviz_html(parse_interactive_html(raw_text))
        if _normalized_html(current_html) == _normalized_html(edited_html):
            raise HtmlGenerationError(
                "HTML 修改失败，模型未产生实际变化，原页面已保留",
                code="edit_no_change",
                detail="candidate_unchanged",
            )
        contract_errors = _edit_contract_errors(current_html, edited_html)
        if contract_errors:
            raise HtmlGenerationError(
                "HTML 修改失败，重生成结果破坏了原页面核心契约，原页面已保留",
                code="edit_contract_changed",
                detail="; ".join(contract_errors),
            )
        yield build_html_progress_payload(
            [
                {"content": "分析当前 HTML 与修改意见", "status": "completed"},
                {"content": "重新生成完整 HTML", "status": "completed"},
            ],
            html_content=edited_html,
        )
        yield HtmlStreamResult(
            html=edited_html,
            degraded=timed_out,
            truncated=False,
            strategy="full_html_regeneration",
            finish_reason=finish_reason,
            source_chars=len(current_html),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            output_chars=len(raw_text),
        )
    except GeneratorExit:
        raise
    except HtmlGenerationError:
        raise
    except Exception as exc:
        logger.warning("edit_html model failed: %s", exc)
        raise HtmlGenerationError(
            "HTML 修改失败，未获得可用页面",
            code="edit_failed",
            detail=str(exc),
        ) from exc


def _has_full_edit_budget(current_html: str) -> bool:
    estimated_capacity = estimated_output_capacity_chars(settings.aetherviz_edit_max_tokens)
    return len(current_html) + FULL_HTML_OUTPUT_RESERVE_CHARS <= estimated_capacity


def _edit_contract_errors(source_html: str, candidate_html: str) -> list[str]:
    errors: list[str] = []
    source_type = _widget_type(source_html)
    candidate_type = _widget_type(candidate_html)
    if source_type and candidate_type != source_type:
        errors.append(f"widget_type_changed:{source_type}->{candidate_type or 'missing'}")

    missing_actions = [
        action for action in _REQUIRED_WIDGET_ACTIONS if action in source_html and action not in candidate_html
    ]
    if missing_actions:
        errors.append(f"widget_actions_missing:{','.join(missing_actions)}")
    return errors


def _widget_type(html: str) -> str | None:
    config = BeautifulSoup(html or "", "html.parser").find("script", id="widget-config")
    if config is None:
        return None
    try:
        payload = json.loads(config.get_text())
    except (TypeError, ValueError):
        return None
    value = payload.get("type") if isinstance(payload, dict) else None
    return str(value) if value else None


def _normalized_html(html: str) -> str:
    return "".join((html or "").split())


def _summarize_edit_stream(items: list[dict[str, Any] | HtmlStreamResult]) -> dict[str, Any]:
    result = next((item for item in reversed(items) if isinstance(item, HtmlStreamResult)), None)
    if result is None:
        return {"completed": False}
    return {
        "completed": True,
        "accepted": True,
        "rolled_back": False,
        "strategy": result.strategy,
        "source_chars": result.source_chars,
        "result_chars": len(result.html),
        "finish_reason": result.finish_reason,
        "truncated": result.truncated,
        "patch_functions": list(result.patch_functions),
        "patch_blocks": list(result.patch_blocks),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "output_chars": result.output_chars or len(result.html),
        "chars_per_output_token": (
            round((result.output_chars or len(result.html)) / result.output_tokens, 3) if result.output_tokens else None
        ),
    }


def _summarize_edit_sse(chunks: list[str]) -> dict[str, Any]:
    events = [line[7:] for chunk in chunks for line in chunk.splitlines() if line.startswith("event: ")]
    return {"event_count": len(events), "events": events, "completed": "html.done" in events}


def _topic_from_context(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return "AI教学动画"
    return str(context.get("topic") or context.get("user_message") or "AI教学动画")
