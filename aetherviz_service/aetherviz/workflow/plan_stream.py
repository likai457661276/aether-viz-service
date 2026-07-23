"""Shared SSE adaptation for planning and revision model streams."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import PlanningStreamResult
from aetherviz_service.aetherviz.api.sse import agent_sse_event


def stream_plan_phase(
    items: Iterable[dict[str, Any] | PlanningStreamResult],
    *,
    run_id: str,
    phase: str,
) -> Iterator[str]:
    result: PlanningStreamResult | None = None
    for item in items:
        if isinstance(item, PlanningStreamResult):
            result = item
        else:
            yield agent_sse_event("plan.delta", run_id=run_id, phase=phase, data=item)
    if result is None:
        raise RuntimeError("planning agent did not return a plan")
    metrics = {
        "planning_elapsed_ms": result.planning_elapsed_ms,
        "first_chunk_elapsed_ms": result.first_chunk_elapsed_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "plan_diagnostics": list(result.plan_diagnostics),
    }
    return result.plan, result.degraded, metrics
