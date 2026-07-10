"""HTML generation workflow."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.html_agent import HtmlGenerationError, HtmlStreamResult, stream_generate_html
from aetherviz_service.aetherviz.agents.repair_agent import (
    RepairStreamResult,
    deterministic_repair_html,
    stream_repair_html,
)
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.tools.validation_report import build_validation_report
from aetherviz_service.config import settings


def run_generate_workflow(
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
    html_factory=None,
    html_stream_factory=None,
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
    try:
        if html_stream_factory is not None:
            for item in html_stream_factory():
                if isinstance(item, HtmlStreamResult):
                    html, degraded = item.html, item.degraded
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
        else:
            html, degraded = html_factory()
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
    yield agent_sse_event(
        "validation.started",
        run_id=run_id,
        phase=phase,
        data={"bytes": len(html.encode("utf-8")), "chars": len(html)},
        metadata=_metadata(metadata, started_at, stage="validation"),
    )
    report = _validate(html)
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
                "bytes": len(html.encode("utf-8")),
                "chars": len(html),
            },
        },
        metadata=_metadata(metadata, started_at, stage="done"),
    )


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
) -> Iterator[str]:
    repaired = False
    deterministic_html = deterministic_repair_html(html, report, plan=plan)
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
        report = _validate(html)
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
            data={"attempt": 1, "strategy": "deterministic", "ok": report["ok"], "summary": report.get("summary")},
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        if report["ok"]:
            return html, report, repaired, metadata["degraded"]

    max_attempts = min(max(settings.aetherviz_max_repair_attempts, 0), 1)
    for attempt in range(max_attempts):
        previous_html = html
        previous_errors = _error_signature(report)
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
        for item in stream_repair_html(
            topic=topic,
            plan=plan,
            raw_html=html,
            report=report,
        ):
            if isinstance(item, RepairStreamResult):
                html, repair_degraded = item.html, item.degraded
                continue
            yield agent_sse_event(
                "html.delta",
                run_id=run_id,
                phase=phase,
                data=item,
                metadata=_metadata(metadata, started_at, stage="repair"),
            )
        metadata["degraded"] = metadata["degraded"] or repair_degraded
        repaired = True
        report = _validate(html)
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
            data={"attempt": attempt_number, "strategy": "model", "ok": report["ok"], "summary": report.get("summary")},
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        if report["ok"]:
            break
        if html == previous_html or _error_signature(report) == previous_errors:
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


def _validate(html: str) -> dict[str, Any]:
    return build_validation_report(html)


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
