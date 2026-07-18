"""Hybrid deterministic and LLM-assisted IR routing service."""

from __future__ import annotations

import logging
import time
from typing import Any

from aetherviz_service.aetherviz.agents.model_factory import has_primary_llm_config
from aetherviz_service.aetherviz.ir.registry import DEFAULT_IR_REGISTRY, IRBackendRegistry
from aetherviz_service.aetherviz.ir.router.contracts import IRRouteAssessment, IRRouteDecision
from aetherviz_service.aetherviz.ir.router.llm_judge import judge_ir_route
from aetherviz_service.aetherviz.workflow.representation_spec import representation_spec_fingerprint
from aetherviz_service.config import settings

logger = logging.getLogger(__name__)


def resolve_generation_route(
    plan: dict[str, Any], *, registry: IRBackendRegistry = DEFAULT_IR_REGISTRY
) -> IRRouteDecision:
    started = time.monotonic()
    fingerprint = representation_spec_fingerprint(plan)
    candidates = registry.assess(plan)
    eligible = tuple(item for item in candidates if item.eligible and not item.exclusion_reasons)
    if not eligible:
        return _decision(
            None,
            "deterministic",
            1.0,
            fingerprint,
            candidates,
            ("没有 IR 后端满足计划所需能力，使用直接 HTML",),
            started,
        )

    top = eligible[0]
    second_score = eligible[1].score if len(eligible) > 1 else 0.0
    margin = top.score - second_score
    prior = _prior_backend(plan, registry)
    prior_conflict = prior is not None and prior != top.backend_key
    ambiguous = (
        top.score < settings.aetherviz_ir_router_deterministic_threshold
        or margin < settings.aetherviz_ir_router_min_margin
        or prior_conflict
    )
    deterministic_reasons = (*top.reasons, *(('knowledge_profile_prior_conflict',) if prior_conflict else ()))
    if not ambiguous or not settings.aetherviz_ir_router_enabled or not has_primary_llm_config():
        return _decision(
            top.backend_key,
            "deterministic",
            top.score,
            fingerprint,
            candidates,
            deterministic_reasons,
            started,
        )

    try:
        judged = judge_ir_route(plan, candidates, registry.backends())
        selected = _llm_selected(judged.get("selected_backend"))
        confidence = _confidence(judged.get("confidence"))
        llm_capabilities = _capabilities(judged.get("required_capabilities"))
        selected_assessment = next((item for item in eligible if item.backend_key == selected), None)
        accepted = (
            (selected is None or selected_assessment is not None)
            and confidence >= settings.aetherviz_ir_router_confidence_threshold
        )
        evidence = tuple(str(item)[:180] for item in judged.get("evidence", []) if str(item).strip())
        if accepted and not settings.aetherviz_ir_router_shadow_mode:
            return _decision(
                selected,
                "llm_judge",
                confidence,
                fingerprint,
                candidates,
                evidence,
                started,
                llm_invoked=True,
                llm_accepted=True,
                llm_selected_backend=selected,
                llm_confidence=confidence,
                llm_required_capabilities=llm_capabilities,
            )
        fallback = "shadow_mode" if accepted else "llm_selection_rejected"
        return _decision(
            top.backend_key,
            "deterministic",
            top.score,
            fingerprint,
            candidates,
            (*deterministic_reasons, *evidence),
            started,
            llm_invoked=True,
            llm_accepted=accepted,
            fallback=fallback,
            llm_selected_backend=selected,
            llm_confidence=confidence,
            llm_required_capabilities=llm_capabilities,
        )
    except Exception as exc:
        logger.warning("IR route judge failed; using deterministic candidate: %s", exc)
        return _decision(
            top.backend_key,
            "fallback",
            top.score,
            fingerprint,
            candidates,
            deterministic_reasons,
            started,
            llm_invoked=True,
            fallback=type(exc).__name__,
        )


def _prior_backend(plan: dict[str, Any], registry: IRBackendRegistry) -> str | None:
    profile = plan.get("knowledge_profile") if isinstance(plan.get("knowledge_profile"), dict) else {}
    representation = str(profile.get("representation_type") or "")
    if not representation:
        return None
    backend = registry.resolve(plan)
    if backend is None:
        return "direct"
    assessment = backend.assess(plan) if backend.assess is not None else None
    if assessment is not None and not assessment.eligible and representation == "geometric_construction":
        # This legacy prior covers both continuous Euclidean construction and
        # discrete regular-polygon convergence. Let plan capabilities decide
        # between those geometry backends without forcing an LLM arbitration.
        return None
    return backend.key


def _confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _llm_selected(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


def _capabilities(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value[:12]:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:64])
    return tuple(result)


def _decision(
    selected: str | None,
    source: str,
    confidence: float,
    fingerprint: str,
    candidates: tuple[IRRouteAssessment, ...],
    reasons: tuple[str, ...],
    started: float,
    *,
    llm_invoked: bool = False,
    llm_accepted: bool = False,
    fallback: str | None = None,
    llm_selected_backend: str | None = None,
    llm_confidence: float | None = None,
    llm_required_capabilities: tuple[str, ...] = (),
) -> IRRouteDecision:
    return IRRouteDecision(
        selected_backend=selected,
        source=source,
        confidence=round(confidence, 3),
        plan_fingerprint=fingerprint,
        candidates=candidates,
        reasons=reasons,
        llm_invoked=llm_invoked,
        llm_accepted=llm_accepted,
        fallback=fallback,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        llm_selected_backend=llm_selected_backend,
        llm_confidence=None if llm_confidence is None else round(llm_confidence, 3),
        llm_required_capabilities=llm_required_capabilities,
    )
