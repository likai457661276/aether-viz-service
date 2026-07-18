"""Shared HTML validation and repair delivery pipeline."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.contracts.html_stream import (
    HtmlGenerationError,
    HtmlStreamResult,
    is_retryable_edit_error,
)
from aetherviz_service.aetherviz.contracts.layout import (
    LAYOUT_CONTRACT_VERSION,
    assemble_layout_contract,
)
from aetherviz_service.aetherviz.contracts.repair.deterministic import (
    deterministic_can_address,
    deterministic_repair_html,
)
from aetherviz_service.aetherviz.contracts.repair.function import stream_repair_functions
from aetherviz_service.aetherviz.contracts.repair.model import stream_repair_html
from aetherviz_service.aetherviz.contracts.repair.session import (
    RepairSession,
    accept_hard_repair_candidate,
    error_signature,
)
from aetherviz_service.aetherviz.contracts.validation.report import build_validation_report
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
    "abstract_svg_marker_scale_risk",
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


def run_html_pipeline(
    *,
    run_id: str,
    phase: str,
    start_event: str,
    topic: str,
    plan: dict[str, Any],
    html_stream_factory: Callable[[], Iterator[dict[str, Any] | HtmlStreamResult]],
    generation_backend: str = "direct",
    emit_start_event: bool = True,
    candidate_guard: Callable[[str], list[str]] | None = None,
    initial_metadata: dict[str, Any] | None = None,
    include_plan_in_repair: bool | None = None,
    reasoning_enabled: bool | None = None,
) -> Iterator[str]:
    started_at = time.monotonic()
    if include_plan_in_repair is None:
        include_plan_in_repair = phase != "edit_html"
    if reasoning_enabled is None:
        reasoning_enabled = (
            settings.aetherviz_edit_enable_thinking
            if phase == "edit_html"
            else phase == "generate" and settings.aetherviz_html_enable_thinking
        )
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
        "reasoning_enabled": reasoning_enabled,
        **(initial_metadata or {}),
    }
    if emit_start_event:
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
                metadata["generation_backend_fallback"] = item.generation_fallback
                if item.intent_passed is not None:
                    metadata["intent_passed"] = item.intent_passed
                    metadata["intent_soft_failed"] = list(item.intent_soft_failed)
                    metadata["intent_check_count"] = item.intent_check_count
                    metadata["intent_summary"] = item.intent_summary
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
            retryable=_is_retryable_pipeline_error(phase, exc.code),
            metadata=_metadata(metadata, started_at, stage="generate"),
        )
        return
    if html is None or business_html is None:
        yield agent_error_event(
            run_id=run_id,
            phase=phase,
            code="runtime_error",
            message="HTML 生成未返回结果",
            retryable=_is_retryable_pipeline_error(phase, "runtime_error"),
        )
        return
    metadata["degraded"] = degraded
    metadata["truncated"] = source_truncated
    if candidate_guard is not None:
        guard_errors = candidate_guard(business_html)
        if guard_errors:
            yield agent_error_event(
                run_id=run_id,
                phase=phase,
                code="edit_intent_not_satisfied",
                message="HTML 修改结果未满足本次编辑验收条件，原页面已保留",
                detail="; ".join(guard_errors[:8]),
                retryable=_is_retryable_pipeline_error(phase, "edit_intent_not_satisfied"),
                metadata=_metadata(metadata, started_at, stage="edit_guard"),
            )
            return
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
            include_plan_in_repair=include_plan_in_repair,
        )
        html = assemble_layout_contract(business_html, plan)
        if not report["ok"]:
            if not source_truncated:
                yield agent_sse_event(
                    "html.repair_source",
                    run_id=run_id,
                    phase=phase,
                    data={
                        "html": html,
                        "report": report,
                        "renderable": False,
                        "message": "保留完整失败候选稿，供后续 edit_html 定向修复",
                    },
                    metadata=_metadata(metadata, started_at, stage="validation"),
                )
            yield agent_error_event(
                run_id=run_id,
                phase=phase,
                code="validation_failed",
                message="HTML 生成结果未通过确定性检查",
                detail=report["summary"],
                retryable=_is_retryable_pipeline_error(phase, "validation_failed"),
                metadata=_metadata(metadata, started_at, stage="validation"),
            )
            return

    if phase in {"generate", "edit_html"} and report["ok"] and _quality_warning_types(report):
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

    if candidate_guard is not None:
        guard_errors = candidate_guard(business_html)
        if guard_errors:
            yield agent_error_event(
                run_id=run_id,
                phase=phase,
                code="edit_intent_lost_after_repair",
                message="自动修复未能保留本次编辑结果，原页面已保留",
                detail="; ".join(guard_errors[:8]),
                retryable=_is_retryable_pipeline_error(phase, "edit_intent_lost_after_repair"),
                metadata=_metadata(metadata, started_at, stage="edit_guard"),
            )
            return

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
                "generation_backend_fallback": metadata.get("generation_backend_fallback"),
                "generation_route_source": metadata.get("generation_route_source"),
                "generation_route_confidence": metadata.get("generation_route_confidence"),
                "generation_route_llm_invoked": metadata.get("generation_route_llm_invoked", False),
                "generation_route_llm_accepted": metadata.get("generation_route_llm_accepted", False),
                "generation_route_fallback": metadata.get("generation_route_fallback"),
                "generation_route_elapsed_ms": metadata.get("generation_route_elapsed_ms", 0),
                "generation_route_plan_fingerprint": metadata.get("generation_route_plan_fingerprint"),
                "generation_route_reasons": metadata.get("generation_route_reasons", []),
                "generation_route_candidates": metadata.get("generation_route_candidates", []),
                "generation_route_llm_selected_backend": metadata.get(
                    "generation_route_llm_selected_backend"
                ),
                "generation_route_llm_confidence": metadata.get("generation_route_llm_confidence"),
                "generation_route_llm_required_capabilities": metadata.get(
                    "generation_route_llm_required_capabilities", []
                ),
                "layout_contract_version": LAYOUT_CONTRACT_VERSION,
                "truncated": metadata.get("truncated", False),
                "bytes": len(html.encode("utf-8")),
                "chars": len(html),
                "model_chars": len(business_html),
                "assembled_chars": len(html),
                "assembly_overhead_chars": len(html) - len(business_html),
                "assembly_count": 1,
                "edit_strategy": metadata.get("edit_strategy"),
                "edit_diagnosis_strategy": metadata.get("edit_diagnosis_strategy"),
                "edit_diagnosis_confidence": metadata.get("edit_diagnosis_confidence"),
                "edit_diagnosis_degraded": metadata.get("edit_diagnosis_degraded", False),
                "intent_passed": metadata.get("intent_passed"),
                "intent_soft_failed": metadata.get("intent_soft_failed", []),
                "intent_check_count": metadata.get("intent_check_count", 0),
                "intent_summary": metadata.get("intent_summary", ""),
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
    include_plan_in_repair: bool = True,
) -> Iterator[str]:
    session = RepairSession(
        deterministic_can_address_fn=deterministic_can_address,
        function_repair_stream=stream_repair_functions,
        model_repair_stream=stream_repair_html,
    )
    return (yield from session.run(
        run_id=run_id,
        phase=phase,
        topic=topic,
        plan=plan,
        html=html,
        report=report,
        metadata=metadata,
        started_at=started_at,
        source_truncated=source_truncated,
        include_plan_in_repair=include_plan_in_repair,
    ))


def _error_signature(report: dict[str, Any]) -> tuple[str, ...]:
    return error_signature(report)


def _accept_hard_repair_candidate(
    *,
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    candidate_truncated: bool,
) -> tuple[bool, str | None]:
    return accept_hard_repair_candidate(
        baseline_report=baseline_report,
        candidate_report=candidate_report,
        candidate_truncated=candidate_truncated,
    )


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
    runner = _traced_validate if settings.langsmith_tracing and get_current_run_tree() is not None else _validate_impl
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
        "warning_types": sorted(str(item.get("type")) for item in report.get("warnings", []) if isinstance(item, dict)),
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


def _is_retryable_pipeline_error(phase: str, code: str) -> bool:
    return phase == "edit_html" and is_retryable_edit_error(code)
