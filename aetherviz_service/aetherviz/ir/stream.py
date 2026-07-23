"""Shared IR JSON streaming with deadline, truncation detection, and bounded full retries."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage

from aetherviz_service.aetherviz.agents.model_factory import create_chat_model, extract_llm_text
from aetherviz_service.aetherviz.contracts.html_stream import HtmlGenerationError
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)

# Transport / truncation failures that warrant one whole IR regeneration.
RETRYABLE_IR_STREAM_ERROR_CODES = frozenset(
    {
        "ir_stream_interrupted",
        "ir_stream_timeout",
        "ir_stream_truncated",
    }
)

# Complex IR backends use the stronger HTML model for structured and HTML repairs.
COMPLEX_IR_REPAIR_BACKENDS = frozenset(
    {
        "recomposition_scene",
        "constraint_geometry_scene",
    }
)


@dataclass(frozen=True)
class IRStreamResult:
    text: str
    timed_out: bool = False
    truncated_by_limit: bool = False
    attempt: int = 1


def is_retryable_ir_stream_error(code: str) -> bool:
    return code in RETRYABLE_IR_STREAM_ERROR_CODES


def uses_strong_ir_repair_model(generation_backend: str) -> bool:
    return generation_backend in COMPLEX_IR_REPAIR_BACKENDS


def looks_like_incomplete_json(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return True
    return False


def raise_if_incomplete_ir_stream(result: IRStreamResult, *, label: str = "IR") -> None:
    """Raise a retryable error when the stream stopped with incomplete JSON."""
    if not looks_like_incomplete_json(result.text):
        return
    if result.timed_out:
        code = "ir_stream_timeout"
        detail = "deadline_exceeded"
    elif result.truncated_by_limit:
        code = "ir_stream_truncated"
        detail = "max_chars_exceeded"
    else:
        code = "ir_stream_interrupted"
        detail = "incomplete_json"
    raise HtmlGenerationError(
        f"{label} 流式输出不完整，已停止本轮生成",
        code=code,
        detail=detail,
    )


def stream_ir_json(
    messages: Sequence[BaseMessage],
    *,
    response_schema: dict[str, Any] | None,
    max_chars: int,
    model_kind: str = "scene",
    enforce_deadline: bool = True,
    allow_full_retry: bool = True,
    label: str = "IR",
) -> IRStreamResult:
    """Stream one IR JSON response, optionally retrying once on incomplete output.

    Full retries reuse ``AETHERVIZ_HTML_STREAM_MAX_RETRIES`` semantics and only cover
    transport-like interruptions / JSON truncation — not deterministic validation failures.
    """
    max_attempts = 1
    if allow_full_retry:
        max_attempts += max(settings.aetherviz_html_stream_max_retries, 0)
    last = IRStreamResult(text="")
    for attempt in range(1, max_attempts + 1):
        last = _stream_once(
            messages,
            response_schema=response_schema,
            max_chars=max_chars,
            model_kind=model_kind,
            enforce_deadline=enforce_deadline,
            attempt=attempt,
        )
        if not looks_like_incomplete_json(last.text):
            return last
        if attempt >= max_attempts:
            break
        logger.warning(
            "%s stream incomplete on attempt %s/%s (timed_out=%s truncated=%s); retrying full generation",
            label,
            attempt,
            max_attempts,
            last.timed_out,
            last.truncated_by_limit,
        )
    raise_if_incomplete_ir_stream(last, label=label)
    return last


def _stream_once(
    messages: Sequence[BaseMessage],
    *,
    response_schema: dict[str, Any] | None,
    max_chars: int,
    model_kind: str,
    enforce_deadline: bool,
    attempt: int,
) -> IRStreamResult:
    raw_text = ""
    timed_out = False
    truncated_by_limit = False
    deadline = (
        time.monotonic() + max(settings.aetherviz_html_timeout_seconds, 1) if enforce_deadline else None
    )
    try:
        stream = create_chat_model(model_kind, response_schema=response_schema).stream(list(messages))
        for chunk in stream:
            if deadline is not None and time.monotonic() > deadline:
                timed_out = True
                break
            text = extract_llm_text(chunk)
            if not text:
                continue
            raw_text += text
            if len(raw_text) > max_chars:
                truncated_by_limit = True
                break
    except GeneratorExit:
        raise
    except Exception as exc:
        logger.warning("strict %s schema unavailable; using JSON mode: %s", model_kind, exc)
        raw_text = ""
        timed_out = False
        truncated_by_limit = False
        for chunk in create_chat_model(model_kind).stream(list(messages)):
            if deadline is not None and time.monotonic() > deadline:
                timed_out = True
                break
            text = extract_llm_text(chunk)
            if not text:
                continue
            raw_text += text
            if len(raw_text) > max_chars:
                truncated_by_limit = True
                break
    return IRStreamResult(
        text=raw_text,
        timed_out=timed_out,
        truncated_by_limit=truncated_by_limit,
        attempt=attempt,
    )
