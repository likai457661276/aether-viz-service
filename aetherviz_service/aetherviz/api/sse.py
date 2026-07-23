"""SSE helpers for the AetherViz workflow."""

from __future__ import annotations

import json
from typing import Any

_langsmith_trace_ids: dict[str, str] = {}


def register_langsmith_trace_id(run_id: str, trace_id: str | None) -> None:
    if trace_id:
        _langsmith_trace_ids[run_id] = trace_id


def unregister_langsmith_trace_id(run_id: str) -> None:
    _langsmith_trace_ids.pop(run_id, None)


def agent_sse_event(
    event: str,
    *,
    run_id: str,
    phase: str,
    data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    payload = {
        "event": event,
        "run_id": run_id,
        "phase": phase,
        "data": data or {},
        "metadata": {
            "attempts": 0,
            "repaired": False,
            "degraded": False,
            "validation_warnings": [],
            **(metadata or {}),
        },
    }
    trace_id = _langsmith_trace_ids.get(run_id)
    if trace_id:
        payload["langsmith_trace_id"] = trace_id
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def agent_error_event(
    *,
    run_id: str,
    phase: str,
    code: str,
    message: str,
    detail: str | None = None,
    retryable: bool = False,
    metadata: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> str:
    return agent_sse_event(
        "error",
        run_id=run_id,
        phase=phase,
        data={
            "code": code,
            "message": message,
            "detail": detail or "",
            "retryable": retryable,
            **({"diagnostics": diagnostics} if diagnostics else {}),
        },
        metadata=metadata,
    )
