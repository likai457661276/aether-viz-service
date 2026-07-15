"""HTML generation workflow."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.function_repair_agent import FunctionRepairResult, stream_repair_functions
from aetherviz_service.aetherviz.agents.html_agent import HtmlGenerationError, HtmlStreamResult, stream_generate_html
from aetherviz_service.aetherviz.agents.recomposition_scene_agent import stream_generate_recomposition_html
from aetherviz_service.aetherviz.agents.repair_agent import RepairStreamResult, stream_repair_html
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.tools.deterministic_repair import (
    deterministic_can_address,
    deterministic_repair_html,
)
from aetherviz_service.aetherviz.tools.function_patch import (
    repair_function_targets,
    target_functions_from_report,
)
from aetherviz_service.aetherviz.tools.layout_contract import (
    LAYOUT_CONTRACT_VERSION,
    assemble_layout_contract,
)
from aetherviz_service.aetherviz.tools.validation_report import build_validation_report
from aetherviz_service.config import settings

QUALITY_REPAIR_WARNING_TYPES = {
    "unformatted_dynamic_value",
    "missing_numeric_descriptor",
    "hardcoded_numeric_step",
    "scattered_visible_precision",
    "svg_visual_center_mismatch",
    "static_viewbox_for_variable_svg",
    "abstract_svg_text_scale_risk",
    "abstract_svg_stroke_scale_risk",
    "mixed_svg_unit_system",
    "missing_stage_shrink_guard",
    "missing_animation_controller_fallback",
    "unchecked_animation_node_registry",
    "gsap_mutates_serialized_state",
    "duplicate_geometry_transform_encoding",
    "quantized_animation_accumulator",
    "no_op_set_speed",
    "animation_controller_bypass",
}

CANDIDATE_FATAL_ERROR_TYPES = {
    "js_syntax",
    "missing_runtime_ready",
    "truncated_model_output",
}


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
    profile = approved_plan.get("knowledge_profile")
    representation = profile.get("representation_type") if isinstance(profile, dict) else None
    if representation == "geometric_recomposition":
        html_stream_factory = partial(stream_generate_recomposition_html, topic, approved_plan)
        generation_backend = "recomposition_scene"
    else:
        html_stream_factory = partial(stream_generate_html, topic, approved_plan)
        generation_backend = "direct"
    yield from _run_html_workflow(
        run_id=run_id,
        phase="generate",
        start_event="html.generation_started",
        topic=topic,
        plan=approved_plan,
        html_stream_factory=html_stream_factory,
        generation_backend=generation_backend,
    )


def _run_html_workflow(
    *,
    run_id: str,
    phase: str,
    start_event: str,
    topic: str,
    plan: dict[str, Any],
    html_stream_factory: Callable[[], Iterator[dict[str, Any] | HtmlStreamResult]],
    generation_backend: str = "direct",
) -> Iterator[str]:
    started_at = time.monotonic()
    metadata = {
        "attempts": 1,
        "generation_attempts": 1,
        "repair_attempts": 0,
        "repaired": False,
        "degraded": False,
        "validation_warnings": [],
        "stage": "generate",
        "elapsed_ms": 0,
        "generation_backend": generation_backend,
        "reasoning_enabled": phase == "generate" and settings.aetherviz_html_enable_thinking,
    }
    yield agent_sse_event(
        start_event,
        run_id=run_id,
        phase=phase,
        data={
            "message": "html_agent 开始生成 HTML",
            "reasoning_enabled": metadata["reasoning_enabled"],
        },
        metadata=_metadata(metadata, started_at, stage="generate"),
    )
    business_html = None
    html = None
    degraded = False
    source_truncated = False
    try:
        for item in html_stream_factory():
            if isinstance(item, HtmlStreamResult):
                business_html, degraded = item.html, item.degraded
                html = assemble_layout_contract(business_html, plan)
                source_truncated = item.truncated
                metadata["reasoning_elapsed_ms"] = item.reasoning_elapsed_ms
                metadata["first_chunk_elapsed_ms"] = item.first_chunk_elapsed_ms
                metadata["generation_elapsed_ms"] = item.generation_elapsed_ms
                metadata["edit_strategy"] = item.strategy
                metadata["model_finish_reason"] = item.finish_reason
                metadata["source_business_chars"] = item.source_chars
                metadata["patch_functions"] = list(item.patch_functions)
                metadata["patch_blocks"] = list(item.patch_blocks)
                metadata["model_input_tokens"] = item.input_tokens
                metadata["model_output_tokens"] = item.output_tokens
                metadata["model_output_chars"] = item.output_chars or len(item.html)
                yield agent_sse_event(
                    "html.delta",
                    run_id=run_id,
                    phase=phase,
                    data={
                        "delta": "",
                        "bytes": len(html.encode("utf-8")),
                        "chars": len(html),
                        "reasoning_active": False,
                        "reasoning_elapsed_ms": item.reasoning_elapsed_ms,
                        "first_chunk_elapsed_ms": item.first_chunk_elapsed_ms,
                        "generation_elapsed_ms": item.generation_elapsed_ms,
                    },
                    metadata=_metadata(metadata, started_at, stage="generate"),
                )
                continue
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data=item,
                metadata=_metadata(metadata, started_at, stage="generate"),
            )
    except HtmlGenerationError as exc:
        yield agent_error_event(
            run_id=run_id,
            phase=phase,
            code=exc.code,
            message=exc.message,
            detail=exc.detail,
            metadata=_metadata(metadata, started_at, stage="generate"),
        )
        return
    if html is None or business_html is None:
        yield agent_error_event(
            run_id=run_id,
            phase=phase,
            code="runtime_error",
            message="HTML 生成未返回结果",
        )
        return
    metadata["degraded"] = degraded
    metadata["truncated"] = source_truncated
    yield agent_sse_event(
        "validation.started",
        run_id=run_id,
        phase=phase,
        data={"bytes": len(html.encode("utf-8")), "chars": len(html)},
        metadata=_metadata(metadata, started_at, stage="validation"),
    )
    report = _validate(html, truncated=source_truncated, plan=plan, model_html=business_html)
    yield from _emit_validation_events(
        run_id=run_id,
        phase=phase,
        report=report,
        metadata=metadata,
        started_at=started_at,
    )

    metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
    if not report["ok"]:
        business_html, report, metadata["repaired"], metadata["degraded"] = yield from _attempt_repair_loop(
            run_id=run_id,
            phase=phase,
            topic=topic,
            plan=plan,
            html=business_html,
            report=report,
            metadata=metadata,
            started_at=started_at,
            source_truncated=source_truncated,
        )
        html = assemble_layout_contract(business_html, plan)
        if not report["ok"]:
            yield agent_error_event(
                run_id=run_id,
                phase=phase,
                code="validation_failed",
                message="HTML 生成结果未通过确定性检查",
                detail=report["summary"],
                metadata=_metadata(metadata, started_at, stage="validation"),
            )
            return

    if (
        phase in {"generate", "edit_html"}
        and report["ok"]
        and _quality_warning_types(report)
    ):
        business_html, report, quality_repaired, quality_degraded = yield from _attempt_quality_repair(
            run_id=run_id,
            phase=phase,
            plan=plan,
            html=business_html,
            report=report,
            metadata=metadata,
            started_at=started_at,
        )
        html = assemble_layout_contract(business_html, plan)
        metadata["repaired"] = metadata["repaired"] or quality_repaired
        metadata["degraded"] = metadata["degraded"] or quality_degraded
        metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]

    yield agent_sse_event(
        "html.done",
        run_id=run_id,
        phase=phase,
        data={
            "html": html,
            "metadata": {
                "topic": topic,
                "attempts": metadata["attempts"],
                "generation_attempts": metadata["generation_attempts"],
                "repair_attempts": metadata["repair_attempts"],
                "repaired": metadata["repaired"],
                "degraded": metadata["degraded"],
                "validation_warnings": metadata["validation_warnings"],
                "render_mode": plan.get("interactive_type"),
                "subject": plan.get("subject"),
                "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                "reasoning_elapsed_ms": metadata.get("reasoning_elapsed_ms", 0),
                "first_chunk_elapsed_ms": metadata.get("first_chunk_elapsed_ms", 0),
                "generation_elapsed_ms": metadata.get("generation_elapsed_ms", 0),
                "generation_backend": metadata["generation_backend"],
                "layout_contract_version": LAYOUT_CONTRACT_VERSION,
                "truncated": metadata.get("truncated", False),
                "bytes": len(html.encode("utf-8")),
                "chars": len(html),
                "model_chars": len(business_html),
                "assembled_chars": len(html),
                "assembly_overhead_chars": len(html) - len(business_html),
                "assembly_count": 1,
                "edit_strategy": metadata.get("edit_strategy"),
                "model_finish_reason": metadata.get("model_finish_reason"),
                "source_business_chars": metadata.get("source_business_chars", 0),
                "patch_functions": metadata.get("patch_functions", []),
                "patch_blocks": metadata.get("patch_blocks", []),
                "model_input_tokens": metadata.get("model_input_tokens"),
                "model_output_tokens": metadata.get("model_output_tokens"),
                "model_output_chars": metadata.get("model_output_chars", len(business_html)),
                "chars_per_output_token": (
                    round(metadata.get("model_output_chars", len(business_html)) / metadata["model_output_tokens"], 3)
                    if metadata.get("model_output_tokens")
                    else None
                ),
            },
        },
        metadata=_metadata(metadata, started_at, stage="done"),
    )


def _attempt_quality_repair(
    *,
    run_id: str,
    phase: str,
    plan: dict[str, Any],
    html: str,
    report: dict[str, Any],
    metadata: dict[str, Any],
    started_at: float,
) -> Iterator[str]:
    """Apply deterministic normalization to selected quality warnings.

    Quality heuristics must not trigger a synchronous full-document model rewrite.
    Remaining warnings are delivered with the valid HTML for offline or opt-in review.
    """
    if settings.aetherviz_max_repair_attempts <= 0:
        return html, report, False, False

    baseline_html = html
    baseline_report = report
    baseline_quality = _quality_warning_types(report)
    repaired = False
    quality_report = _quality_only_report(baseline_report)
    deterministic_candidate = deterministic_repair_html(baseline_html, quality_report, plan=plan)
    if deterministic_candidate != baseline_html:
        assembled_candidate = assemble_layout_contract(deterministic_candidate, plan)
        deterministic_report = _validate(assembled_candidate, plan=plan, model_html=deterministic_candidate)
        deterministic_quality = _quality_warning_types(deterministic_report)
        if deterministic_report["ok"] and len(deterministic_quality) < len(baseline_quality):
            attempt_number = _next_repair_attempt(metadata)
            yield agent_sse_event(
                "repair.started",
                run_id=run_id,
                phase=phase,
                data={
                    "attempt": attempt_number,
                    "repair_attempt": attempt_number,
                    "strategy": "quality-deterministic",
                    "warnings": quality_report["warnings"][:5],
                },
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data={
                    "delta": "",
                    "bytes": len(assembled_candidate.encode("utf-8")),
                    "chars": len(assembled_candidate),
                },
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
            yield from _emit_validation_events(
                run_id=run_id,
                phase=phase,
                report=deterministic_report,
                metadata=metadata,
                started_at=started_at,
                stage="repair",
            )
            yield agent_sse_event(
                "repair.done",
                run_id=run_id,
                phase=phase,
                data={
                    "attempt": attempt_number,
                    "repair_attempt": attempt_number,
                    "strategy": "quality-deterministic",
                    "ok": True,
                    "accepted": True,
                    "remaining_warning_types": sorted(deterministic_quality),
                    "bytes": len(assembled_candidate.encode("utf-8")),
                    "chars": len(assembled_candidate),
                },
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
            baseline_html = deterministic_candidate
            baseline_report = deterministic_report
            baseline_quality = deterministic_quality
            repaired = True
            if not baseline_quality:
                return baseline_html, baseline_report, True, False

    return baseline_html, baseline_report, repaired, False


def _quality_only_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        **report,
        "summary": "发现可自动改进的通用展示质量风险",
        "errors": [],
        "warnings": [
            warning
            for warning in report.get("warnings", [])
            if isinstance(warning, dict) and warning.get("type") in QUALITY_REPAIR_WARNING_TYPES
        ],
    }


def _hard_error_only_report(report: dict[str, Any]) -> dict[str, Any]:
    errors = [error for error in report.get("errors", []) if isinstance(error, dict)]
    return {
        **report,
        "ok": not errors,
        "summary": f"发现 {len(errors)} 个硬性错误" if errors else "硬性检查通过",
        "errors": errors,
        "warnings": [],
        "checks": {
            name: {**check, "warnings": []}
            for name, check in (report.get("checks") or {}).items()
            if isinstance(check, dict) and check.get("errors")
        },
    }


def _attempt_repair_loop(
    *,
    run_id: str,
    phase: str,
    topic: str,
    plan: dict[str, Any],
    html: str,
    report: dict[str, Any],
    metadata: dict[str, Any],
    started_at: float,
    source_truncated: bool,
) -> Iterator[str]:
    repaired = False
    if source_truncated:
        metadata["repair_rejection_reason"] = "source_truncated"
        return html, report, False, metadata["degraded"]
    hard_report = _hard_error_only_report(report)
    deterministic_html = html
    if deterministic_can_address(hard_report):
        deterministic_html = _run_deterministic_repair(html, hard_report, plan)
    if deterministic_html != html:
        previous_html = html
        previous_report = report
        attempt_number = _next_repair_attempt(metadata)
        yield agent_sse_event(
            "repair.started",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt_number,
                "repair_attempt": attempt_number,
                "strategy": "deterministic",
                "summary": hard_report.get("summary"),
            },
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        assembled_html = assemble_layout_contract(deterministic_html, plan)
        yield agent_sse_event(
            "html.delta",
            run_id=run_id,
            phase=phase,
            data={"delta": "", "bytes": len(assembled_html.encode("utf-8")), "chars": len(assembled_html)},
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        candidate_report = _validate(
            assembled_html,
            truncated=source_truncated,
            plan=plan,
            model_html=deterministic_html,
        )
        accepted, rejection_reason = _accept_hard_repair_candidate(
            baseline_report=previous_report,
            candidate_report=candidate_report,
            candidate_truncated=source_truncated,
        )
        if accepted:
            html = deterministic_html
            report = candidate_report
            repaired = True
            yield from _emit_validation_events(
                run_id=run_id,
                phase=phase,
                report=report,
                metadata=metadata,
                started_at=started_at,
                stage="repair",
            )
        else:
            html = previous_html
            report = previous_report
            yield _emit_candidate_validation_event(
                run_id=run_id,
                phase=phase,
                report=candidate_report,
                metadata=metadata,
                started_at=started_at,
                rejection_reason=rejection_reason,
                will_continue=True,
            )
            rollback_html = assemble_layout_contract(html, plan)
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data={"delta": "", "bytes": len(rollback_html.encode("utf-8")), "chars": len(rollback_html)},
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
        metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
        yield agent_sse_event(
            "repair.done",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt_number,
                "repair_attempt": attempt_number,
                "strategy": "deterministic",
                "ok": report["ok"],
                "accepted": accepted,
                "rejection_reason": rejection_reason,
                "summary": report.get("summary"),
                "bytes": len(assemble_layout_contract(html, plan).encode("utf-8")),
                "chars": len(assemble_layout_contract(html, plan)),
            },
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        if accepted and report["ok"]:
            return html, report, repaired, metadata["degraded"]

    max_attempts = min(max(settings.aetherviz_max_repair_attempts, 0), 1)
    if max_attempts and target_functions_from_report(report):
        html, report, function_repaired, function_degraded = yield from _attempt_function_repair(
            run_id=run_id,
            phase=phase,
            plan=plan,
            html=html,
            report=report,
            metadata=metadata,
            started_at=started_at,
        )
        repaired = repaired or function_repaired
        metadata["degraded"] = metadata["degraded"] or function_degraded
        metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
        if report["ok"]:
            return html, report, repaired, metadata["degraded"]

    for _attempt in range(max_attempts):
        had_prior_repair = repaired
        previous_html = html
        previous_report = report
        previous_degraded = metadata["degraded"]
        previous_truncated = metadata.get("truncated", False)
        attempt_number = _next_repair_attempt(metadata)
        hard_report = _hard_error_only_report(report)
        yield agent_sse_event(
            "repair.started",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt_number,
                "repair_attempt": attempt_number,
                "strategy": "model",
                "summary": hard_report.get("summary"),
                "errors": hard_report.get("errors", [])[:5],
            },
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        repair_degraded = False
        repair_truncated = False
        for item in stream_repair_html(
            topic=topic,
            plan=plan,
            raw_html=html,
            report=hard_report,
        ):
            if isinstance(item, RepairStreamResult):
                html, repair_degraded = item.html, item.degraded
                repair_truncated = item.truncated
                assembled_html = assemble_layout_contract(html, plan)
                yield agent_sse_event(
                    "html.delta",
                    run_id=run_id,
                    phase=phase,
                    data={
                        "delta": "",
                        "bytes": len(assembled_html.encode("utf-8")),
                        "chars": len(assembled_html),
                    },
                    metadata=_metadata(metadata, started_at, stage="repair"),
                )
                continue
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data=item,
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
        candidate_unchanged = _normalized_repair_candidate(html) == _normalized_repair_candidate(
            previous_html
        )
        assembled_html = assemble_layout_contract(html, plan)
        candidate_report = (
            previous_report
            if candidate_unchanged
            else _validate(assembled_html, truncated=repair_truncated, plan=plan, model_html=html)
        )
        if not candidate_unchanged and not candidate_report["ok"] and not repair_truncated:
            post_hard_report = _hard_error_only_report(candidate_report)
            post_model_html = html
            if deterministic_can_address(post_hard_report):
                post_model_html = _run_deterministic_repair(html, post_hard_report, plan)
            if post_model_html != html:
                html = post_model_html
                assembled_html = assemble_layout_contract(html, plan)
                yield agent_sse_event(
                    "html.delta",
                    run_id=run_id,
                    phase=phase,
                    data={
                        "delta": "",
                        "bytes": len(assembled_html.encode("utf-8")),
                        "chars": len(assembled_html),
                    },
                    metadata=_metadata(metadata, started_at, stage="repair"),
                )
                candidate_report = _validate(
                    assembled_html,
                    truncated=repair_truncated,
                    plan=plan,
                    model_html=html,
                )
        if candidate_unchanged:
            accepted, rejection_reason = False, "unchanged_candidate"
        else:
            accepted, rejection_reason = _accept_hard_repair_candidate(
                baseline_report=previous_report,
                candidate_report=candidate_report,
                candidate_truncated=repair_truncated,
            )
        candidate_error_types = list(_error_signature(candidate_report))
        if accepted:
            report = candidate_report
            repaired = True
            metadata["degraded"] = previous_degraded or repair_degraded
            metadata["truncated"] = False
            yield from _emit_validation_events(
                run_id=run_id,
                phase=phase,
                report=report,
                metadata=metadata,
                started_at=started_at,
                stage="repair",
            )
        else:
            html = previous_html
            report = previous_report
            repaired = had_prior_repair
            metadata["degraded"] = previous_degraded
            metadata["truncated"] = previous_truncated
            metadata["validation_warnings"] = [
                warning["message"] for warning in report.get("warnings", [])
            ]
            metadata["repair_rejected"] = True
            metadata["repair_rejected_error_types"] = candidate_error_types
            metadata["repair_rejection_reason"] = rejection_reason
            yield _emit_candidate_validation_event(
                run_id=run_id,
                phase=phase,
                report=candidate_report,
                metadata=metadata,
                started_at=started_at,
                rejection_reason=rejection_reason,
                will_continue=False,
            )
            rollback_html = assemble_layout_contract(html, plan)
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data={"delta": "", "bytes": len(rollback_html.encode("utf-8")), "chars": len(rollback_html)},
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
        metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
        yield agent_sse_event(
            "repair.done",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt_number,
                "repair_attempt": attempt_number,
                "strategy": "model",
                "ok": report["ok"],
                "accepted": accepted,
                "stalled": rejection_reason in {"no_hard_error_reduction", "unchanged_candidate"},
                "rejection_reason": rejection_reason,
                "remaining_error_types": candidate_error_types,
                "summary": report.get("summary"),
                "bytes": len(assemble_layout_contract(html, plan).encode("utf-8")),
                "chars": len(assemble_layout_contract(html, plan)),
                "model_chars": len(html),
            },
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        if report["ok"]:
            break
        if not accepted or html == previous_html:
            break
    return html, report, repaired, metadata["degraded"]


def _attempt_function_repair(
    *,
    run_id: str,
    phase: str,
    plan: dict[str, Any],
    html: str,
    report: dict[str, Any],
    metadata: dict[str, Any],
    started_at: float,
) -> Iterator[str]:
    baseline_html = html
    baseline_report = report
    attempt_number = _next_repair_attempt(metadata)
    yield agent_sse_event(
        "repair.started",
        run_id=run_id,
        phase=phase,
        data={
            "attempt": attempt_number,
            "repair_attempt": attempt_number,
            "strategy": "function-model",
            "functions": list(repair_function_targets(html, report)),
            "errors": report.get("errors", [])[:5],
        },
        metadata=_metadata(metadata, started_at, stage="repair"),
    )
    candidate = baseline_html
    applied: tuple[str, ...] = ()
    degraded = False
    patch_errors: tuple[str, ...] = ()
    for item in stream_repair_functions(raw_html=baseline_html, report=_hard_error_only_report(report)):
        if isinstance(item, FunctionRepairResult):
            candidate = item.html
            applied = item.applied
            degraded = item.degraded
            patch_errors = item.errors
            continue
        yield agent_sse_event(
            "html.delta",
            run_id=run_id,
            phase=phase,
            data=item,
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
    assembled_candidate = assemble_layout_contract(candidate, plan)
    candidate_report = _validate(assembled_candidate, plan=plan, model_html=candidate)
    accepted, rejection_reason = _accept_hard_repair_candidate(
        baseline_report=baseline_report,
        candidate_report=candidate_report,
        candidate_truncated=False,
    )
    accepted = accepted and candidate != baseline_html and bool(applied)
    if not accepted and rejection_reason is None:
        rejection_reason = "no_function_patch_applied"
    if accepted:
        html = candidate
        report = candidate_report
        yield from _emit_validation_events(
            run_id=run_id,
            phase=phase,
            report=report,
            metadata=metadata,
            started_at=started_at,
            stage="repair",
        )
    else:
        html = baseline_html
        report = baseline_report
        yield _emit_candidate_validation_event(
            run_id=run_id,
            phase=phase,
            report=candidate_report,
            metadata=metadata,
            started_at=started_at,
            rejection_reason=rejection_reason,
            will_continue=True,
        )
    assembled_result = assemble_layout_contract(html, plan)
    yield agent_sse_event(
        "html.delta",
        run_id=run_id,
        phase=phase,
        data={"delta": "", "bytes": len(assembled_result.encode("utf-8")), "chars": len(assembled_result)},
        metadata=_metadata(metadata, started_at, stage="repair"),
    )
    yield agent_sse_event(
        "repair.done",
        run_id=run_id,
        phase=phase,
        data={
            "attempt": attempt_number,
            "repair_attempt": attempt_number,
            "strategy": "function-model",
            "ok": report["ok"],
            "accepted": accepted,
            "rejection_reason": rejection_reason,
            "functions": list(applied),
            "patch_errors": list(patch_errors),
            "remaining_error_types": list(_error_signature(report)),
            "bytes": len(assembled_result.encode("utf-8")),
            "chars": len(assembled_result),
        },
        metadata=_metadata(metadata, started_at, stage="repair"),
    )
    return html, report, accepted, degraded if accepted else False


def _error_signature(report: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(error.get("type") or error.get("message") or "unknown")
            for error in report.get("errors", [])
            if isinstance(error, dict)
        )
    )


def _normalized_repair_candidate(html: str) -> str:
    """Normalize transport-only fences before detecting a no-op repair."""
    normalized = (html or "").strip().replace("\r\n", "\n")
    if normalized.startswith("```"):
        newline = normalized.find("\n")
        normalized = normalized[newline + 1 :] if newline >= 0 else ""
    if normalized.endswith("```"):
        normalized = normalized[:-3]
    return normalized.strip()


def _accept_hard_repair_candidate(
    *,
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    candidate_truncated: bool,
) -> tuple[bool, str | None]:
    if candidate_truncated:
        return False, "truncated_candidate"
    baseline_errors = set(_error_signature(baseline_report))
    candidate_errors = set(_error_signature(candidate_report))
    new_fatal_errors = (candidate_errors - baseline_errors) & CANDIDATE_FATAL_ERROR_TYPES
    if new_fatal_errors:
        return False, "new_fatal_errors:" + ",".join(sorted(new_fatal_errors))
    if candidate_report.get("ok"):
        return True, None
    if len(candidate_report.get("errors", [])) < len(baseline_report.get("errors", [])):
        return True, None
    return False, "no_hard_error_reduction"


def _next_repair_attempt(metadata: dict[str, Any]) -> int:
    metadata["repair_attempts"] = int(metadata.get("repair_attempts", 0)) + 1
    metadata["attempts"] = int(metadata.get("generation_attempts", 1)) + metadata["repair_attempts"]
    return metadata["repair_attempts"]


def _quality_warning_types(report: dict[str, Any]) -> set[str]:
    return {
        str(warning.get("type"))
        for warning in report.get("warnings", [])
        if isinstance(warning, dict) and warning.get("type") in QUALITY_REPAIR_WARNING_TYPES
    }


def _emit_validation_events(
    *,
    run_id: str,
    phase: str,
    report: dict[str, Any],
    metadata: dict[str, Any],
    started_at: float,
    stage: str = "validation",
) -> Iterator[str]:
    for check_name, check in (report.get("checks") or {}).items():
        yield agent_sse_event(
            "validation.check",
            run_id=run_id,
            phase=phase,
            data={"check": check_name, "report": _report_summary(check)},
            metadata=_metadata(metadata, started_at, stage=stage),
        )
    yield agent_sse_event(
        "validation.report",
        run_id=run_id,
        phase=phase,
        data={"report": _report_summary(report)},
        metadata=_metadata(metadata, started_at, stage=stage),
    )


def _emit_candidate_validation_event(
    *,
    run_id: str,
    phase: str,
    report: dict[str, Any],
    metadata: dict[str, Any],
    started_at: float,
    rejection_reason: str | None,
    will_continue: bool,
) -> str:
    return agent_sse_event(
        "validation.candidate",
        run_id=run_id,
        phase=phase,
        data={
            "report": _report_summary(report),
            "accepted": False,
            "rolled_back": True,
            "will_continue": will_continue,
            "rejection_reason": rejection_reason,
        },
        metadata=_metadata(metadata, started_at, stage="repair"),
    )


def _validate(
    html: str,
    *,
    truncated: bool = False,
    plan: dict[str, Any] | None = None,
    model_html: str | None = None,
) -> dict[str, Any]:
    runner = (
        _traced_validate
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _validate_impl
    )
    return runner(html, truncated=truncated, plan=plan, model_html=model_html)


@traceable(
    name="aetherviz.validation",
    run_type="tool",
    metadata={"component": "aetherviz", "stage": "validation"},
    process_inputs=lambda inputs: {
        "chars": len(inputs.get("html") or ""),
        "bytes": len((inputs.get("html") or "").encode("utf-8")),
        "model_chars": len(inputs.get("model_html") or inputs.get("html") or ""),
        "assembled_chars": len(inputs.get("html") or ""),
        "truncated": inputs.get("truncated", False),
    },
    process_outputs=lambda report: {
        "ok": report.get("ok"),
        "summary": report.get("summary"),
        "error_types": list(_error_signature(report)),
        "warning_types": sorted(
            str(item.get("type")) for item in report.get("warnings", []) if isinstance(item, dict)
        ),
    },
)
def _traced_validate(
    html: str,
    *,
    truncated: bool = False,
    plan: dict[str, Any] | None = None,
    model_html: str | None = None,
) -> dict[str, Any]:
    return _validate_impl(html, truncated=truncated, plan=plan, model_html=model_html)


def _validate_impl(
    html: str,
    *,
    truncated: bool = False,
    plan: dict[str, Any] | None = None,
    model_html: str | None = None,
) -> dict[str, Any]:
    report = build_validation_report(html, plan=plan, model_html=model_html)
    if not truncated:
        return report
    error = {
        "type": "truncated_model_output",
        "message": "模型输出缺少原始 </html> 结束标签，自动闭合结果必须经过模型修复",
        "line": None,
    }
    report["ok"] = False
    report["severity"] = "error"
    report["errors"] = [error]
    report["summary"] = "发现 1 个硬性错误"
    return report


def _run_deterministic_repair(html: str, report: dict[str, Any], plan: dict[str, Any]) -> str:
    runner = (
        _traced_deterministic_repair
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else deterministic_repair_html
    )
    return runner(html, report, plan=plan)


@traceable(
    name="aetherviz.deterministic_repair",
    run_type="tool",
    metadata={"component": "aetherviz", "stage": "deterministic_repair"},
    process_inputs=lambda inputs: {
        "source_chars": len(inputs.get("html") or ""),
        "error_types": [item.get("type") for item in (inputs.get("report") or {}).get("errors", [])],
    },
    process_outputs=lambda output: {"chars": len(output), "bytes": len(output.encode("utf-8"))},
)
def _traced_deterministic_repair(
    html: str,
    report: dict[str, Any],
    *,
    plan: dict[str, Any],
) -> str:
    return deterministic_repair_html(html, report, plan=plan)


def _summarize_sse_trace(chunks: list[str]) -> dict[str, Any]:
    events: list[str] = []
    repairs: list[dict[str, Any]] = []
    final: dict[str, Any] = {}
    for chunk in chunks:
        event = next((line[7:] for line in chunk.splitlines() if line.startswith("event: ")), "")
        if event:
            events.append(event)
        data_line = next((line[6:] for line in chunk.splitlines() if line.startswith("data: ")), "")
        if event in {"repair.done", "html.done", "error"} and data_line:
            try:
                payload = json.loads(data_line)
            except ValueError:
                continue
            if event == "repair.done":
                repair_data = payload.get("data") or {}
                repairs.append(
                    {
                        key: repair_data.get(key)
                        for key in (
                            "strategy",
                            "ok",
                            "accepted",
                            "stalled",
                            "remaining_error_types",
                            "chars",
                            "bytes",
                        )
                        if key in repair_data
                    }
                )
            elif event == "html.done":
                done_data = payload.get("data") or {}
                final = {"event": event, **(done_data.get("metadata") or {})}
            else:
                error_data = payload.get("data") or {}
                final = {
                    "event": event,
                    "code": error_data.get("code"),
                    "message": error_data.get("message"),
                    "detail": error_data.get("detail"),
                    "metadata": payload.get("metadata") or {},
                }
    return {"event_count": len(events), "events": events, "repairs": repairs, "final": final}


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": report.get("ok"),
        "summary": report.get("summary"),
        "errors": report.get("errors", [])[:5],
        "warnings": report.get("warnings", [])[:5],
    }


def _metadata(metadata: dict[str, Any], started_at: float, *, stage: str) -> dict[str, Any]:
    return {
        **metadata,
        "stage": stage,
        "elapsed_ms": int((time.monotonic() - started_at) * 1000),
    }
