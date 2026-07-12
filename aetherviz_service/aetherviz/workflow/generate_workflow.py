"""HTML generation workflow."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from aetherviz_service.aetherviz.agents.html_agent import HtmlGenerationError, HtmlStreamResult, stream_generate_html
from aetherviz_service.aetherviz.agents.repair_agent import RepairStreamResult, stream_repair_html
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.tools.deterministic_repair import deterministic_repair_html
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
    "static_viewbox_for_variable_svg",
    "abstract_svg_text_scale_risk",
    "abstract_svg_stroke_scale_risk",
    "mixed_svg_unit_system",
    "missing_stage_shrink_guard",
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
    yield from _run_html_workflow(
        run_id=run_id,
        phase="generate",
        start_event="html.generation_started",
        topic=topic,
        plan=approved_plan,
        html_stream_factory=lambda: stream_generate_html(topic, approved_plan),
    )


def _run_html_workflow(
    *,
    run_id: str,
    phase: str,
    start_event: str,
    topic: str,
    plan: dict[str, Any],
    html_stream_factory: Callable[[], Iterator[dict[str, Any] | HtmlStreamResult]],
) -> Iterator[str]:
    started_at = time.monotonic()
    metadata = {
        "attempts": 1,
        "repaired": False,
        "degraded": False,
        "validation_warnings": [],
        "stage": "generate",
        "elapsed_ms": 0,
        "generation_backend": "direct",
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
    html = None
    degraded = False
    source_truncated = False
    try:
        for item in html_stream_factory():
            if isinstance(item, HtmlStreamResult):
                html, degraded = assemble_layout_contract(item.html, plan), item.degraded
                source_truncated = item.truncated
                metadata["reasoning_elapsed_ms"] = item.reasoning_elapsed_ms
                metadata["first_chunk_elapsed_ms"] = item.first_chunk_elapsed_ms
                metadata["generation_elapsed_ms"] = item.generation_elapsed_ms
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
    if html is None:
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
    report = _validate(html, truncated=source_truncated, plan=plan)
    yield from _emit_validation_events(
        run_id=run_id,
        phase=phase,
        report=report,
        metadata=metadata,
        started_at=started_at,
    )

    metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
    if not report["ok"]:
        html, report, metadata["repaired"], metadata["degraded"] = yield from _attempt_repair_loop(
            run_id=run_id,
            phase=phase,
            topic=topic,
            plan=plan,
            html=html,
            report=report,
            metadata=metadata,
            started_at=started_at,
            source_truncated=source_truncated,
        )
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

    if phase == "generate" and report["ok"] and _quality_warning_types(report):
        html, report, quality_repaired, quality_degraded = yield from _attempt_quality_repair(
            run_id=run_id,
            phase=phase,
            topic=topic,
            plan=plan,
            html=html,
            report=report,
            metadata=metadata,
            started_at=started_at,
        )
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
                "repaired": metadata["repaired"],
                "degraded": metadata["degraded"],
                "validation_warnings": metadata["validation_warnings"],
                "render_mode": plan.get("interactive_type"),
                "subject": plan.get("subject"),
                "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                "reasoning_elapsed_ms": metadata.get("reasoning_elapsed_ms", 0),
                "first_chunk_elapsed_ms": metadata.get("first_chunk_elapsed_ms", 0),
                "generation_elapsed_ms": metadata.get("generation_elapsed_ms", 0),
                "generation_backend": "direct",
                "layout_contract_version": LAYOUT_CONTRACT_VERSION,
                "truncated": metadata.get("truncated", False),
                "bytes": len(html.encode("utf-8")),
                "chars": len(html),
            },
        },
        metadata=_metadata(metadata, started_at, stage="done"),
    )


def _attempt_quality_repair(
    *,
    run_id: str,
    phase: str,
    topic: str,
    plan: dict[str, Any],
    html: str,
    report: dict[str, Any],
    metadata: dict[str, Any],
    started_at: float,
) -> Iterator[str]:
    """Try one non-blocking model repair for generic presentation risks.

    Quality warnings never reject a usable document. The candidate is accepted only
    when it remains valid and reduces the selected warning set; otherwise the
    original HTML is returned unchanged.
    """
    if settings.aetherviz_max_repair_attempts <= 0:
        return html, report, False, False

    original_html = html
    original_report = report
    original_quality = _quality_warning_types(report)
    quality_report = {
        **report,
        "summary": "发现可自动改进的通用展示质量风险",
        "errors": [],
        "warnings": [
            warning
            for warning in report.get("warnings", [])
            if isinstance(warning, dict) and warning.get("type") in QUALITY_REPAIR_WARNING_TYPES
        ],
    }
    deterministic_candidate = assemble_layout_contract(
        deterministic_repair_html(original_html, quality_report, plan=plan), plan
    )
    if deterministic_candidate != original_html:
        deterministic_report = _validate(deterministic_candidate, plan=plan)
        deterministic_quality = _quality_warning_types(deterministic_report)
        if deterministic_report["ok"] and len(deterministic_quality) < len(original_quality):
            metadata["attempts"] += 1
            yield agent_sse_event(
                "repair.started",
                run_id=run_id,
                phase=phase,
                data={"attempt": 1, "strategy": "quality-deterministic", "warnings": quality_report["warnings"][:5]},
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data={
                    "delta": "",
                    "bytes": len(deterministic_candidate.encode("utf-8")),
                    "chars": len(deterministic_candidate),
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
                    "attempt": 1,
                    "strategy": "quality-deterministic",
                    "ok": True,
                    "accepted": True,
                    "remaining_warning_types": sorted(deterministic_quality),
                    "bytes": len(deterministic_candidate.encode("utf-8")),
                    "chars": len(deterministic_candidate),
                },
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
            return deterministic_candidate, deterministic_report, True, False
    metadata["attempts"] += 1
    yield agent_sse_event(
        "repair.started",
        run_id=run_id,
        phase=phase,
        data={
            "attempt": 1,
            "strategy": "quality-model",
            "summary": quality_report["summary"],
            "warnings": quality_report["warnings"][:5],
        },
        metadata=_metadata(metadata, started_at, stage="repair"),
    )

    candidate = original_html
    candidate_degraded = False
    candidate_truncated = False
    for item in stream_repair_html(
        topic=topic,
        plan=plan,
        raw_html=original_html,
        report=quality_report,
    ):
        if isinstance(item, RepairStreamResult):
            candidate = assemble_layout_contract(item.html, plan)
            candidate_degraded = item.degraded
            candidate_truncated = item.truncated
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data={
                    "delta": "",
                    "bytes": len(candidate.encode("utf-8")),
                    "chars": len(candidate),
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

    candidate_report = _validate(candidate, truncated=candidate_truncated, plan=plan)
    candidate_quality = _quality_warning_types(candidate_report)
    accepted = (
        candidate != original_html
        and candidate_report["ok"]
        and len(candidate_quality) < len(original_quality)
    )
    if accepted:
        html, report = candidate, candidate_report
        yield from _emit_validation_events(
            run_id=run_id,
            phase=phase,
            report=report,
            metadata=metadata,
            started_at=started_at,
            stage="repair",
        )
    else:
        html, report = original_html, original_report

    yield agent_sse_event(
        "html.delta",
        run_id=run_id,
        phase=phase,
        data={"delta": "", "bytes": len(html.encode("utf-8")), "chars": len(html)},
        metadata=_metadata(metadata, started_at, stage="repair"),
    )

    yield agent_sse_event(
        "repair.done",
        run_id=run_id,
        phase=phase,
        data={
            "attempt": 1,
            "strategy": "quality-model",
            "ok": accepted,
            "accepted": accepted,
            "remaining_warning_types": sorted(_quality_warning_types(report)),
            "bytes": len(html.encode("utf-8")),
            "chars": len(html),
        },
        metadata=_metadata(metadata, started_at, stage="repair"),
    )
    return html, report, accepted, candidate_degraded if accepted else False


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
    deterministic_html = _run_deterministic_repair(html, report, plan)
    if deterministic_html != html:
        metadata["attempts"] += 1
        yield agent_sse_event(
            "repair.started",
            run_id=run_id,
            phase=phase,
            data={"attempt": 1, "strategy": "deterministic", "summary": report.get("summary")},
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        html = deterministic_html
        repaired = True
        yield agent_sse_event(
            "html.delta",
            run_id=run_id,
            phase=phase,
            data={"delta": "", "bytes": len(html.encode("utf-8")), "chars": len(html)},
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        report = _validate(html, truncated=source_truncated, plan=plan)
        yield from _emit_validation_events(
            run_id=run_id,
            phase=phase,
            report=report,
            metadata=metadata,
            started_at=started_at,
            stage="repair",
        )
        metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
        yield agent_sse_event(
            "repair.done",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": 1,
                "strategy": "deterministic",
                "ok": report["ok"],
                "summary": report.get("summary"),
                "bytes": len(html.encode("utf-8")),
                "chars": len(html),
            },
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        if report["ok"]:
            return html, report, repaired, metadata["degraded"]

    max_attempts = min(max(settings.aetherviz_max_repair_attempts, 0), 1)
    for attempt in range(max_attempts):
        had_prior_repair = repaired
        previous_html = html
        previous_report = report
        previous_errors = _error_signature(report)
        previous_degraded = metadata["degraded"]
        previous_truncated = metadata.get("truncated", False)
        metadata["attempts"] += 1
        attempt_number = attempt + 1 + int(repaired)
        yield agent_sse_event(
            "repair.started",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt_number,
                "strategy": "model",
                "summary": report.get("summary"),
                "errors": report.get("errors", [])[:5],
            },
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        repair_degraded = False
        repair_truncated = False
        for item in stream_repair_html(
            topic=topic,
            plan=plan,
            raw_html=html,
            report=report,
        ):
            if isinstance(item, RepairStreamResult):
                html, repair_degraded = assemble_layout_contract(item.html, plan), item.degraded
                repair_truncated = item.truncated
                yield agent_sse_event(
                    "html.delta",
                    run_id=run_id,
                    phase=phase,
                    data={
                        "delta": "",
                        "bytes": len(html.encode("utf-8")),
                        "chars": len(html),
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
        metadata["degraded"] = metadata["degraded"] or repair_degraded
        metadata["truncated"] = repair_truncated
        repaired = True
        report = _validate(html, truncated=repair_truncated, plan=plan)
        yield from _emit_validation_events(
            run_id=run_id,
            phase=phase,
            report=report,
            metadata=metadata,
            started_at=started_at,
            stage="repair",
        )
        metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
        stalled = not report["ok"] and _error_signature(report) == previous_errors
        accepted = not stalled
        candidate_error_types = list(_error_signature(report))
        if stalled:
            html = previous_html
            report = previous_report
            repaired = had_prior_repair
            metadata["degraded"] = previous_degraded
            metadata["truncated"] = previous_truncated
            metadata["validation_warnings"] = [
                warning["message"] for warning in report.get("warnings", [])
            ]
            metadata["repair_stalled"] = True
            metadata["repair_stalled_error_types"] = candidate_error_types
        yield agent_sse_event(
            "repair.done",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt_number,
                "strategy": "model",
                "ok": report["ok"],
                "accepted": accepted,
                "stalled": stalled,
                "remaining_error_types": candidate_error_types,
                "summary": report.get("summary"),
                "bytes": len(html.encode("utf-8")),
                "chars": len(html),
            },
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        if report["ok"]:
            break
        if stalled or html == previous_html:
            break
    return html, report, repaired, metadata["degraded"]


def _error_signature(report: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(error.get("type") or error.get("message") or "unknown")
            for error in report.get("errors", [])
            if isinstance(error, dict)
        )
    )


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


def _validate(html: str, *, truncated: bool = False, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    runner = (
        _traced_validate
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else _validate_impl
    )
    return runner(html, truncated=truncated, plan=plan)


@traceable(
    name="aetherviz.validation",
    run_type="tool",
    metadata={"component": "aetherviz", "stage": "validation"},
    process_inputs=lambda inputs: {
        "chars": len(inputs.get("html") or ""),
        "bytes": len((inputs.get("html") or "").encode("utf-8")),
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
def _traced_validate(html: str, *, truncated: bool = False, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    return _validate_impl(html, truncated=truncated, plan=plan)


def _validate_impl(html: str, *, truncated: bool = False, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    report = build_validation_report(html, plan=plan)
    if not truncated:
        return report
    error = {
        "type": "truncated_model_output",
        "message": "模型输出缺少原始 </html> 结束标签，自动闭合结果必须经过模型修复",
        "line": None,
    }
    report["ok"] = False
    report["severity"] = "error"
    report["errors"] = [*report.get("errors", []), error]
    report["summary"] = f"发现 {len(report['errors'])} 个硬性错误"
    return report


def _run_deterministic_repair(html: str, report: dict[str, Any], plan: dict[str, Any]) -> str:
    runner = (
        _traced_deterministic_repair
        if settings.langsmith_tracing and get_current_run_tree() is not None
        else deterministic_repair_html
    )
    return assemble_layout_contract(runner(html, report, plan=plan), plan)


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
