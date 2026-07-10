"""HTML generation workflow."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.html_agent import HtmlGenerationError, HtmlStreamResult, stream_generate_html
from aetherviz_service.aetherviz.agents.instructions import build_interactive_generation_prompt
from aetherviz_service.aetherviz.agents.repair_agent import RepairStreamResult, stream_repair_html
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.sandbox.artifacts import SandboxArtifacts
from aetherviz_service.aetherviz.sandbox.manager import SandboxManager
from aetherviz_service.aetherviz.tools.validation_report import build_validation_report
from aetherviz_service.config import settings


def run_generate_workflow(
    *,
    run_id: str,
    topic: str,
    approved_plan: dict[str, Any],
    sandbox: SandboxManager,
    artifacts: SandboxArtifacts,
) -> Iterator[str]:
    yield from _run_html_workflow(
        run_id=run_id,
        phase="generate",
        start_event="html.generation_started",
        topic=topic,
        plan=approved_plan,
        sandbox=sandbox,
        artifacts=artifacts,
        html_stream_factory=lambda: stream_generate_html(topic, approved_plan),
        original_prompt=build_interactive_generation_prompt(topic, approved_plan),
    )


def _run_html_workflow(
    *,
    run_id: str,
    phase: str,
    start_event: str,
    topic: str,
    plan: dict[str, Any],
    sandbox: SandboxManager,
    artifacts: SandboxArtifacts,
    html_factory=None,
    html_stream_factory=None,
    original_prompt: str = "",
) -> Iterator[str]:
    started_at = time.monotonic()
    metadata = {
        "attempts": 1,
        "repaired": False,
        "degraded": False,
        "validation_warnings": [],
        "stage": "generate",
        "elapsed_ms": 0,
    }
    yield agent_sse_event(
        start_event,
        run_id=run_id,
        phase=phase,
        data={"message": "html_agent 开始生成 HTML"},
        metadata=_metadata(metadata, started_at, stage="generate"),
    )
    html = None
    degraded = False
    try:
        if html_stream_factory is not None:
            for item in html_stream_factory():
                if isinstance(item, HtmlStreamResult):
                    html, degraded = item.html, item.degraded
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
    html_path = sandbox.write_html(artifacts, html)
    yield agent_sse_event(
        "sandbox.written",
        run_id=run_id,
        phase=phase,
        data={"html_path": str(html_path), "bytes": len(html.encode("utf-8")), "chars": len(html)},
        metadata=_metadata(metadata, started_at, stage="sandbox"),
    )
    yield agent_sse_event(
        "validation.started",
        run_id=run_id,
        phase=phase,
        data={"html_path": str(html_path)},
        metadata=_metadata(metadata, started_at, stage="validation"),
    )
    report = _validate(html, artifacts)
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
            sandbox=sandbox,
            artifacts=artifacts,
            metadata=metadata,
            started_at=started_at,
            original_prompt=original_prompt,
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
                "artifacts": {
                    "html_path": str(artifacts.html_path),
                    "report_path": str(artifacts.report_path),
                },
            },
        },
        metadata=_metadata(metadata, started_at, stage="done"),
    )
    if metadata["degraded"]:
        yield agent_sse_event(
            "context.compressed",
            run_id=run_id,
            phase=phase,
            data={"context_status": {"status": "compressed", "summary": "大型 HTML 和检查报告已写入沙箱，仅保留摘要。"}},
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
    sandbox: SandboxManager,
    artifacts: SandboxArtifacts,
    metadata: dict[str, Any],
    started_at: float,
    original_prompt: str,
) -> Iterator[str]:
    repaired = False
    max_attempts = max(settings.aetherviz_agent_max_repair_attempts, 0)
    for attempt in range(max_attempts):
        metadata["attempts"] += 1
        yield agent_sse_event(
            "repair.started",
            run_id=run_id,
            phase=phase,
            data={
                "attempt": attempt + 1,
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
            original_prompt=original_prompt,
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
        html_path = sandbox.write_html(artifacts, html, repaired=True)
        yield agent_sse_event(
            "sandbox.written",
            run_id=run_id,
            phase=phase,
            data={"html_path": str(html_path), "bytes": len(html.encode("utf-8")), "chars": len(html), "repaired": True},
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        report = _validate(html, artifacts, html_path=html_path)
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
            data={"attempt": attempt + 1, "ok": report["ok"], "summary": report.get("summary")},
            metadata=_metadata(metadata, started_at, stage="repair"),
        )
        if report["ok"]:
            break
    return html, report, repaired, metadata["degraded"]


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


def _validate(html: str, artifacts: SandboxArtifacts, *, html_path=None) -> dict[str, Any]:
    return build_validation_report(
        html,
        html_path=html_path or artifacts.html_path,
        report_path=artifacts.report_path,
    )


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
