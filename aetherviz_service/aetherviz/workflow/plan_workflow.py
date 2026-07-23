"""Plan workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import approve_plan, stream_create_plan
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan_with_diagnostics
from aetherviz_service.aetherviz.workflow.plan_diagnostics import (
    check_plan_consistency,
    has_consistency_errors,
    merge_serialized_diagnostics,
)
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
    plan_diagnostics = merge_serialized_diagnostics(
        planning_metrics.get("plan_diagnostics"),
        route_preview_metrics.get("plan_diagnostics"),
    )
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
            "plan_diagnostics": plan_diagnostics,
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
    topic = str(plan.get("source_topic") or plan.get("topic") or plan.get("title") or "AI教学动画")
    normalization = normalize_plan_with_diagnostics(
        plan,
        topic,
        str(plan.get("primary_color") or "#22D3EE"),
    )
    approved = approve_plan(normalization.plan)
    post_diagnostics = check_plan_consistency(approved)
    diagnostics = tuple(dict.fromkeys((*normalization.diagnostics, *post_diagnostics)))
    if has_consistency_errors(post_diagnostics):
        yield agent_error_event(
            run_id=run_id,
            phase="approve_plan",
            code="plan_contract_invalid",
            message="教学设计方案存在无法执行的内部引用",
            detail="请根据诊断修订方案后重新确认",
            diagnostics={"plan_diagnostics": [item.as_dict() for item in diagnostics]},
        )
        return
    route = resolve_generation_route(approved, registry=DEFAULT_IR_REGISTRY, allow_llm=False)
    if route.selected_backend is None:
        yield agent_error_event(
            run_id=run_id,
            phase="approve_plan",
            code="plan_route_unavailable",
            message="当前教学设计方案没有可执行的可视化能力组合",
            detail="请调整视图、互动变量或对应关系后重新确认",
            diagnostics={"route": route.as_dict()},
        )
        return
    yield agent_sse_event(
        "plan.approved",
        run_id=run_id,
        phase="approve_plan",
        data={"plan": approved, "status": "approved"},
        metadata={
            "context_status": approved.get("context_status", {"status": "normal"}),
            "plan_diagnostics": [item.as_dict() for item in diagnostics],
            "route_preview_selected_backend": route.selected_backend,
            "route_preview_confidence": route.confidence,
            "route_preview_reasons": list(route.reasons),
        },
    )
