"""Context status policy for agent runs."""

from __future__ import annotations

from typing import Any


def summarize_context_status(
    *,
    phase: str,
    context: dict[str, Any] | None = None,
    degraded: bool = False,
    compressed: bool = False,
) -> dict[str, Any]:
    status = "degraded" if degraded else "compressed" if compressed else "normal"
    return {
        "status": status,
        "phase": phase,
        "summary": "上下文已自动压缩" if status == "compressed" else "上下文充足" if status == "normal" else "上下文不足，需要补充约束",
        "source": "deepagents_context_policy",
        "context_keys": sorted((context or {}).keys()),
    }
