"""Plan workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import PlanningStreamResult, approve_plan, stream_create_plan
from aetherviz_service.aetherviz.api.sse import agent_sse_event


def run_plan_workflow(*, run_id: str, topic: str, context: dict[str, Any] | None = None) -> Iterator[str]:
    yield agent_sse_event(
        "plan.started",
        run_id=run_id,
        phase="plan",
        data={"message": "规划模型开始生成教案计划", "topic": topic},
    )
    plan = None
    degraded = False
    planning_metrics: dict[str, int] = {}
    for item in stream_create_plan(topic, context=context):
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
        yield agent_sse_event("plan.delta", run_id=run_id, phase="plan", data=item)
    if plan is None:
        raise RuntimeError("planning_agent did not return a plan")
    yield agent_sse_event(
        "plan.ready",
        run_id=run_id,
        phase="plan",
        data={"plan": plan, "status": plan.get("status", "draft")},
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
            phase="plan",
            data={"context_status": plan.get("context_status", {"status": "compressed"})},
            metadata={"degraded": degraded},
        )


def run_approve_plan_workflow(*, run_id: str, plan: dict[str, Any]) -> Iterator[str]:
    approved = approve_plan(plan)
    yield agent_sse_event(
        "plan.approved",
        run_id=run_id,
        phase="approve_plan",
        data={"plan": approved, "status": "approved"},
        metadata={"context_status": approved.get("context_status", {"status": "normal"})},
    )
