"""Shared HTML stream result types and progress payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

HTML_SIZE_EVENT_INTERVAL_BYTES = 512
HTML_REASONING_EVENT_INTERVAL_MS = 250

# Edit failures that are suitable for a one-click client retry.
# Unknown codes stay non-retryable so new configuration/request failures do not
# accidentally trigger another model call.
RETRYABLE_EDIT_ERROR_CODES = frozenset(
    {
        "edit_contract_changed",
        "edit_failed",
        "edit_intent_lost_after_repair",
        "edit_intent_not_satisfied",
        "edit_timeout",
        "edit_truncated",
        "runtime_error",
        "validation_failed",
    }
)


def is_retryable_edit_error(code: str) -> bool:
    """Return whether an edit_html error is suitable for client-side auto-retry."""

    return code in RETRYABLE_EDIT_ERROR_CODES


class HtmlGenerationError(Exception):
    """Raised when an HTML producer cannot return usable HTML with a configured LLM."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "generation_failed",
        detail: str = "",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        self.diagnostics = diagnostics or {}
        super().__init__(message)


@dataclass(frozen=True)
class HtmlStreamResult:
    html: str
    degraded: bool
    truncated: bool = False
    reasoning_elapsed_ms: int = 0
    first_chunk_elapsed_ms: int = 0
    generation_elapsed_ms: int = 0
    strategy: str = "full_html"
    finish_reason: str | None = None
    source_chars: int = 0
    patch_functions: tuple[str, ...] = ()
    patch_blocks: tuple[str, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    output_chars: int = 0
    generation_fallback: str | None = None
    ir_repair_attempts: int = 0
    intent_passed: bool | None = None
    intent_soft_failed: tuple[str, ...] = ()
    intent_check_count: int = 0
    intent_summary: str = ""


def build_html_progress_payload(
    steps: list[dict[str, str]],
    *,
    html_content: str | None = None,
) -> dict[str, Any]:
    active_index = next((index for index, step in enumerate(steps) if step["status"] == "in_progress"), None)
    payload = {
        "delta": _format_html_progress_delta(steps),
        "html_steps": steps,
        "active_step_index": active_index,
    }
    if html_content is not None:
        payload.update(build_html_size_payload(html_content))
    return payload


def build_html_size_payload(html_content: str) -> dict[str, Any]:
    """Return the actual accumulated HTML size without returning partial HTML."""

    return {
        "delta": "",
        "bytes": len(html_content.encode("utf-8")),
        "chars": len(html_content),
    }


def build_html_reasoning_payload(elapsed_ms: int, *, active: bool) -> dict[str, Any]:
    """Expose reasoning duration without forwarding private chain-of-thought text."""

    return {
        "delta": "",
        "reasoning_active": active,
        "reasoning_elapsed_ms": max(elapsed_ms, 0),
    }


def _format_html_progress_delta(steps: list[dict[str, str]]) -> str:
    active = next((step for step in steps if step["status"] == "in_progress"), None)
    if active:
        return f"正在{active['content']}"
    if steps and all(step["status"] == "completed" for step in steps):
        return "HTML 生成步骤已完成"
    return "正在准备 HTML 生成"
