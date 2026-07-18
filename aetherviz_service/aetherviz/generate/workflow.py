"""HTML generation workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langsmith import traceable

from aetherviz_service.aetherviz.contracts.pipeline import _summarize_sse_trace, run_html_pipeline
from aetherviz_service.aetherviz.generate.html_agent import stream_generate_html
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.config import settings


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
    yield from _run_generate_workflow_impl(run_id=run_id, topic=topic, approved_plan=approved_plan)


def _run_generate_workflow_impl(
    *,
    run_id: str,
    topic: str,
    approved_plan: dict[str, Any],
) -> Iterator[str]:
    route = resolve_generation_route(approved_plan)
    selection = DEFAULT_IR_REGISTRY.select_for_route(
        route,
        topic=topic,
        plan=approved_plan,
        direct_stream=stream_generate_html,
    )
    yield from run_html_pipeline(
        run_id=run_id,
        phase="generate",
        start_event="html.generation_started",
        topic=topic,
        plan=approved_plan,
        html_stream_factory=selection.stream_factory,
        generation_backend=selection.generation_backend,
        include_plan_in_repair=True,
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
