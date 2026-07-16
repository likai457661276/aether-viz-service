"""Plan revision workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import stream_revise_plan
from aetherviz_service.aetherviz.api.sse import agent_sse_event
from aetherviz_service.aetherviz.workflow.plan_stream import stream_plan_phase


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
    plan, degraded, planning_metrics = yield from stream_plan_phase(
        stream_revise_plan(topic, current_plan=current_plan, message=message, context=context),
        run_id=run_id,
        phase="revise_plan",
    )
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
