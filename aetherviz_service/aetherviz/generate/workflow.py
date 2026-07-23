"""HTML generation workflow."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from langsmith import traceable

from aetherviz_service.aetherviz.contracts.pipeline import _summarize_sse_trace, run_html_pipeline
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.tools.trace_manager import DEFAULT_TRACE_DIR, TraceManager
from aetherviz_service.config import settings
from aetherviz_service.observability.langsmith import mark_current_langsmith_run_error_from_sse

# Tests may override the directory used for JSONL persistence.
_TRACE_OUTPUT_DIR: Path | None = None


def run_generate_workflow(
    *,
    run_id: str,
    topic: str,
    approved_plan: dict[str, Any],
) -> Iterator[str]:
    tracing_enabled = settings.langsmith_tracing and bool((settings.langsmith_api_key or "").strip())
    runner = _traced_run_generate_workflow if tracing_enabled else _run_generate_workflow_impl
    extra = {
        "metadata": {
            "component": "aetherviz",
            "phase": "generate",
            "run_id": run_id,
            "interactive_type": approved_plan.get("interactive_type"),
            "subject": approved_plan.get("subject"),
        }
    }
    if runner is _traced_run_generate_workflow:
        yield from runner(run_id=run_id, topic=topic, approved_plan=approved_plan, langsmith_extra=extra)
        return
    yield from runner(run_id=run_id, topic=topic, approved_plan=approved_plan)


@traceable(
    name="aetherviz.generate_workflow",
    run_type="chain",
    metadata={"component": "aetherviz", "phase": "generate"},
    process_inputs=lambda inputs: {
        "run_id": inputs.get("run_id"),
        "topic": inputs.get("topic"),
        "interactive_type": (inputs.get("approved_plan") or {}).get("interactive_type"),
        "subject": (inputs.get("approved_plan") or {}).get("subject"),
    },
    reduce_fn=lambda chunks: _summarize_sse_trace(chunks),
)
def _traced_run_generate_workflow(
    *,
    run_id: str,
    topic: str,
    approved_plan: dict[str, Any],
) -> Iterator[str]:
    for chunk in _run_generate_workflow_impl(run_id=run_id, topic=topic, approved_plan=approved_plan):
        mark_current_langsmith_run_error_from_sse(chunk)
        yield chunk


def _run_generate_workflow_impl(
    *,
    run_id: str,
    topic: str,
    approved_plan: dict[str, Any],
) -> Iterator[str]:
    trace = TraceManager(output_dir=_TRACE_OUTPUT_DIR or DEFAULT_TRACE_DIR)
    trace.start_trace(request_id=run_id, user_prompt=topic)
    try:
        # Planning happens in an earlier API phase; generate records the approved plan that drives IR.
        trace.start_stage("planning")
        trace.finish_stage(
            "planning",
            {
                "input_prompt": topic,
                "plan_output": _summarize_plan_for_trace(approved_plan),
            },
        )

        trace.start_stage("ir_routing")
        try:
            route = resolve_generation_route(approved_plan)
            selection = DEFAULT_IR_REGISTRY.select_for_route(
                route,
                topic=topic,
                plan=approved_plan,
            )
        except Exception as exc:
            trace.fail_trace("ir_routing", str(exc))
            raise

        routing_metadata = {
            "candidate_ir": [candidate.backend_key for candidate in route.candidates],
            "selected_ir": route.selected_backend,
            "routing_result": route.as_dict(),
            "generation_backend": selection.generation_backend,
        }
        if route.selected_backend is None:
            detail = "；".join(dict.fromkeys(
                reason
                for candidate in route.candidates
                for reason in candidate.exclusion_reasons
            )) or "当前计划没有满足全部必需能力的已注册 IR 后端"
            trace.fail_trace("ir_routing", detail, metadata=routing_metadata)
        else:
            trace.finish_stage("ir_routing", routing_metadata)

        yield from run_html_pipeline(
            run_id=run_id,
            phase="generate",
            start_event="html.generation_started",
            topic=topic,
            plan=approved_plan,
            html_stream_factory=selection.stream_factory,
            generation_backend=selection.generation_backend,
            include_plan_in_repair=True,
            generation_trace=trace,
            initial_metadata={
                "generation_route_source": route.source,
                "generation_route_confidence": route.confidence,
                "generation_route_llm_invoked": route.llm_invoked,
                "generation_route_llm_accepted": route.llm_accepted,
                "generation_route_fallback": route.fallback,
                "generation_route_elapsed_ms": route.elapsed_ms,
                "generation_route_plan_fingerprint": route.plan_fingerprint,
                "generation_route_reasons": list(route.reasons),
                "generation_route_candidates": [candidate.as_dict() for candidate in route.candidates],
                "generation_route_llm_selected_backend": route.llm_selected_backend,
                "generation_route_llm_confidence": route.llm_confidence,
                "generation_route_llm_required_capabilities": list(route.llm_required_capabilities),
            },
        )
    except Exception as exc:
        current = trace.get_trace()
        if current is not None and current.status == "running":
            trace.fail_trace(trace.current_open_stage() or "generation_request", str(exc))
        raise
    finally:
        current = trace.get_trace()
        if current is not None and current.status == "running":
            # Pipeline returned without a terminal status (should be rare; error paths call fail_trace).
            trace.fail_trace(
                trace.current_open_stage() or "final_result",
                "generation ended without a terminal trace status",
            )
        trace.save()


def _summarize_plan_for_trace(plan: dict[str, Any]) -> dict[str, Any]:
    """Compact plan snapshot for offline review without dumping the full document."""

    return {
        "title": plan.get("title"),
        "goal": plan.get("goal"),
        "subject": plan.get("subject"),
        "interactive_type": plan.get("interactive_type"),
        "widget_type": plan.get("widget_type"),
        "learner_level": plan.get("learner_level"),
        "key_points": list(plan.get("key_points") or [])[:8],
        "knowledge_profile": {
            key: (plan.get("knowledge_profile") or {}).get(key)
            for key in (
                "representation_type",
                "pedagogy_pattern",
                "concept_family",
                "discipline_category",
            )
        },
        "recomposition_spec_present": bool(plan.get("recomposition_spec")),
    }
