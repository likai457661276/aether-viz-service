"""Plan workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import approve_plan, stream_create_plan
from aetherviz_service.aetherviz.api.sse import agent_sse_event
from aetherviz_service.aetherviz.workflow.plan_route_preview import maybe_refine_plan_for_route
from aetherviz_service.aetherviz.workflow.plan_stream import stream_plan_phase


def run_plan_workflow(*, run_id: str, topic: str, context: dict[str, Any] | None = None) -> Iterator[str]:
    yield agent_sse_event(
        "plan.started",
        run_id=run_id,
        phase="plan",
        data={"message": "规划模型开始生成教案计划", "topic": topic},
    )
    plan, degraded, planning_metrics = yield from stream_plan_phase(
        stream_create_plan(topic, context=context), run_id=run_id, phase="plan"
    )
    plan, route_preview_metrics = maybe_refine_plan_for_route(plan, topic=topic)
    yield agent_sse_event(
        "plan.ready",
        run_id=run_id,
        phase="plan",
        data={"plan": plan, "status": plan.get("status", "draft")},
        metadata={
            "degraded": degraded,
            "context_status": plan.get("context_status", {"status": "normal"}),
            **planning_metrics,
            **route_preview_metrics,
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
