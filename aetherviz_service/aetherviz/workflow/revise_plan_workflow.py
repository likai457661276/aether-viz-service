"""Plan revision workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import revise_plan
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
        data={"message": "planning_agent 开始修订教案计划", "topic": topic},
    )
    yield agent_sse_event(
        "plan.delta",
        run_id=run_id,
        phase="revise_plan",
        data={"delta": "根据用户修改意见重新生成完整教案计划。"},
    )
    plan, degraded = revise_plan(topic, current_plan=current_plan, message=message, context=context)
    yield agent_sse_event(
        "plan.revised",
        run_id=run_id,
        phase="revise_plan",
        data={"plan": plan, "status": "revised", "revision_summary": plan.get("revision_summary", "")},
        metadata={"degraded": degraded, "context_status": plan.get("context_status", {"status": "normal"})},
    )
    if degraded:
        yield agent_sse_event(
            "context.compressed",
            run_id=run_id,
            phase="revise_plan",
            data={"context_status": plan.get("context_status", {"status": "compressed"})},
            metadata={"degraded": degraded},
        )
