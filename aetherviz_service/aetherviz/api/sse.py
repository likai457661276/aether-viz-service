"""SSE helpers for the Deep Agents workflow."""

from __future__ import annotations

import json
from typing import Any


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
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def agent_error_event(
    *,
    run_id: str,
    phase: str,
    code: str,
    message: str,
    detail: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    return agent_sse_event(
        "error",
        run_id=run_id,
        phase=phase,
        data={"code": code, "message": message, "detail": detail or ""},
        metadata=metadata,
    )
