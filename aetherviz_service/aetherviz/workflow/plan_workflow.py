"""Plan workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import approve_plan, create_plan
from aetherviz_service.aetherviz.api.sse import agent_sse_event


def run_plan_workflow(*, run_id: str, topic: str, context: dict[str, Any] | None = None) -> Iterator[str]:
    yield agent_sse_event(
        "plan.started",
        run_id=run_id,
        phase="plan",
        data={"message": "planning_agent 开始生成教案计划", "topic": topic},
    )
    yield agent_sse_event(
        "plan.delta",
        run_id=run_id,
        phase="plan",
        data={"delta": "分析教学目标、互动类型、舞台结构和控件约束。"},
    )
    plan, degraded = create_plan(topic, context=context)
    yield agent_sse_event(
        "plan.ready",
        run_id=run_id,
        phase="plan",
        data={"plan": plan, "status": plan.get("status", "draft")},
        metadata={"degraded": degraded, "context_status": plan.get("context_status", {"status": "normal"})},
    )
    if degraded:
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
