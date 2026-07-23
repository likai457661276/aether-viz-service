"""Plan workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.planner_agent import approve_plan, stream_create_plan
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_compile import compile_plan_layers, resolve_wire_layers
from aetherviz_service.aetherviz.workflow.plan_diagnostics import (
    check_plan_consistency,
    has_consistency_errors,
    merge_serialized_diagnostics,
)
from aetherviz_service.aetherviz.workflow.plan_layers import extract_generation_spec, extract_teaching_plan
from aetherviz_service.aetherviz.workflow.plan_route_preview import preview_route_for_plan
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
    plan, route_preview_metrics = preview_route_for_plan(plan, topic=topic)
    teaching_plan = extract_teaching_plan(plan)
    plan_diagnostics = merge_serialized_diagnostics(
        planning_metrics.get("plan_diagnostics"),
        route_preview_metrics.get("plan_diagnostics"),
    )
    yield agent_sse_event(
        "plan.ready",
        run_id=run_id,
        phase="plan",
        data={
            # Flat plan kept for legacy frontend compatibility (teaching + deterministic machine).
            "plan": plan,
            "teaching_plan": teaching_plan,
            "status": plan.get("status", "draft"),
        },
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


def run_approve_plan_workflow(
    *,
    run_id: str,
    plan: dict[str, Any] | None = None,
    teaching_plan: dict[str, Any] | None = None,
    generation_spec: dict[str, Any] | None = None,
) -> Iterator[str]:
    teaching, generation, _lifecycle = resolve_wire_layers(
        flat_plan=plan,
        teaching_plan=teaching_plan,
        generation_spec=generation_spec,
    )
    topic_source = teaching or plan or {}
    topic = str(
        topic_source.get("source_topic")
        or topic_source.get("topic")
        or topic_source.get("title")
        or "AI教学动画"
    )
    compiled = compile_plan_layers(
        topic=topic,
        teaching_plan=teaching,
        generation_spec=generation,
        flat_plan=plan,
        allow_llm=True,
    )
    approved = approve_plan(compiled.plan)
    post_diagnostics = check_plan_consistency(approved)
    diagnostics = tuple(dict.fromkeys((*compiled.diagnostics, *post_diagnostics)))
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
    teaching_out = extract_teaching_plan(approved)
    generation_out = extract_generation_spec(approved)
    yield agent_sse_event(
        "plan.approved",
        run_id=run_id,
        phase="approve_plan",
        data={
            "plan": approved,
            "teaching_plan": teaching_out,
            "generation_spec": generation_out,
            "status": "approved",
        },
        metadata={
            "context_status": approved.get("context_status", {"status": "normal"}),
            "plan_diagnostics": [item.as_dict() for item in diagnostics],
            **compiled.metrics,
            "route_preview_selected_backend": route.selected_backend,
            "route_preview_confidence": route.confidence,
            "route_preview_reasons": list(route.reasons),
        },
    )
