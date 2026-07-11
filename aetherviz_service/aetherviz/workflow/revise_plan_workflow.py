"""Plan revision workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import PlanningStreamResult, stream_revise_plan
from aetherviz_service.aetherviz.api.sse import agent_sse_event


def run_revise_plan_workflow(
    *,
    run_id: str,
    topic: str,
    current_plan: dict[str, Any],
    message: str,
    context: dict[str, Any] | None = None,
) -> Iterator[str]:
    yield agent_sse_event(
        "plan.revise_started",
        run_id=run_id,
        phase="revise_plan",
        data={"message": "规划模型开始修订教案计划", "topic": topic},
    )
    plan = None
    degraded = False
    planning_metrics: dict[str, int] = {}
    for item in stream_revise_plan(topic, current_plan=current_plan, message=message, context=context):
        if isinstance(item, PlanningStreamResult):
            plan = item.plan
            degraded = item.degraded
            planning_metrics = {
                "planning_elapsed_ms": item.planning_elapsed_ms,
                "first_chunk_elapsed_ms": item.first_chunk_elapsed_ms,
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "total_tokens": item.total_tokens,
            }
            continue
        yield agent_sse_event("plan.delta", run_id=run_id, phase="revise_plan", data=item)
    if plan is None:
        raise RuntimeError("planning_agent did not return a revised plan")
    yield agent_sse_event(
        "plan.revised",
        run_id=run_id,
        phase="revise_plan",
        data={"plan": plan, "status": "revised", "revision_summary": plan.get("revision_summary", "")},
        metadata={
            "degraded": degraded,
            "context_status": plan.get("context_status", {"status": "normal"}),
            **planning_metrics,
        },
    )
    if plan.get("context_status", {}).get("status") == "compressed":
        yield agent_sse_event(
            "context.compressed",
            run_id=run_id,
            phase="revise_plan",
            data={"context_status": plan.get("context_status", {"status": "compressed"})},
            metadata={"degraded": degraded},
        )
