"""Small helpers for AetherViz SSE payloads."""

from __future__ import annotations

import json


def sse_event(event: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def progress_event(stage: str, message: str, progress: int, **extra: object) -> str:
    data: dict[str, object] = {
        "success": True,
        "stage": stage,
        "message": message,
        "progress": progress,
    }
    data.update(extra)
    return sse_event("progress", data)


def error_event(stage: str, message: str, detail: str) -> str:
    return sse_event(
        "error",
        {
            "success": False,
            "stage": stage,
            "message": message,
            "detail": detail,
        },
    )
