"""Deterministic plan-stage route preview (no LLM refinement).

LLM representation enhancement moved to approve-time ``plan_compile``.
Plan / revise only run a lightweight deterministic routability signal.
"""

from __future__ import annotations

from typing import Any

from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY, IRBackendRegistry
from aetherviz_service.aetherviz.ir.router.service import resolve_generation_route
from aetherviz_service.aetherviz.workflow.plan_contract import normalize_plan_with_diagnostics
from aetherviz_service.aetherviz.workflow.plan_layers import extract_lifecycle_fields, extract_teaching_plan


def preview_route_for_plan(
    plan: dict[str, Any],
    *,
    topic: str,
    registry: IRBackendRegistry = DEFAULT_IR_REGISTRY,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize with deterministic machine derive and preview IR routability.

    Does not call an LLM. Returns the normalized flat plan (teaching + deterministic
    generation spec) plus preview metrics for SSE metadata.
    """
    color = str(plan.get("primary_color") or "#22D3EE")
    normalized_result = normalize_plan_with_diagnostics(plan, topic, color)
    normalized = _preserve_lifecycle_fields(plan, normalized_result.plan)
    preview = resolve_generation_route(normalized, registry=registry, allow_llm=False)
    metrics: dict[str, Any] = {
        "route_preview_attempted": True,
        "route_preview_refined": False,
        "route_preview_refine_attempted": False,
        "route_preview_refine_accepted": False,
        "route_preview_selected_backend": preview.selected_backend,
        "route_preview_confidence": preview.confidence,
        "route_preview_reasons": list(preview.reasons)[:8],
        "plan_diagnostics": normalized_result.diagnostics_as_dicts(),
        "teaching_plan": extract_teaching_plan(normalized),
    }
    return normalized, metrics


# Backward-compatible alias used by older call sites / tests during transition.
def maybe_refine_plan_for_route(
    plan: dict[str, Any],
    *,
    topic: str,
    registry: IRBackendRegistry = DEFAULT_IR_REGISTRY,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deprecated alias: deterministic preview only (LLM refine removed)."""
    return preview_route_for_plan(plan, topic=topic, registry=registry)


def _preserve_lifecycle_fields(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    result = dict(target)
    for field in ("status", "plan_id", "revision_summary", "context_status"):
        if field in source:
            result[field] = source[field]
    # Also keep any lifecycle already on target from normalize.
    for field, value in extract_lifecycle_fields(source).items():
        result.setdefault(field, value)
    return result
