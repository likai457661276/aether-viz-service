"""HTML generation workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.agents.html_agent import generate_html
from aetherviz_service.aetherviz.agents.repair_agent import repair_html
from aetherviz_service.aetherviz.api.sse import agent_error_event, agent_sse_event
from aetherviz_service.aetherviz.sandbox.artifacts import SandboxArtifacts
from aetherviz_service.aetherviz.sandbox.manager import SandboxManager
from aetherviz_service.aetherviz.tools.validation_report import build_validation_report


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
        html_factory=lambda: generate_html(topic, approved_plan),
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
    html_factory,
) -> Iterator[str]:
    metadata = {"attempts": 1, "repaired": False, "degraded": False, "validation_warnings": []}
    yield agent_sse_event(start_event, run_id=run_id, phase=phase, data={"message": "html_agent 开始生成 HTML"})
    html, degraded = html_factory()
    metadata["degraded"] = degraded
    html_path = sandbox.write_html(artifacts, html)
    yield agent_sse_event(
        "sandbox.written",
        run_id=run_id,
        phase=phase,
        data={"html_path": str(html_path), "bytes": len(html.encode("utf-8")), "chars": len(html)},
        metadata=metadata,
    )
    report = _validate(html, artifacts)
    yield agent_sse_event("validation.started", run_id=run_id, phase=phase, data={"html_path": str(html_path)}, metadata=metadata)
    yield agent_sse_event("validation.report", run_id=run_id, phase=phase, data={"report": report}, metadata=metadata)

    repaired = False
    attempts = 1
    while not report["ok"] and attempts <= 2:
        yield agent_sse_event(
            "repair.started",
            run_id=run_id,
            phase=phase,
            data={"attempt": attempts, "report": _report_summary(report)},
            metadata={**metadata, "attempts": attempts},
        )
        html, repair_degraded = repair_html(topic=topic, plan=plan, raw_html=html, report=report)
        repaired = True
        attempts += 1
        metadata.update({"attempts": attempts, "repaired": True, "degraded": bool(metadata["degraded"] or repair_degraded)})
        repair_path = sandbox.write_html(artifacts, html, repaired=True)
        report = _validate(html, artifacts, html_path=repair_path)
        yield agent_sse_event(
            "repair.done",
            run_id=run_id,
            phase=phase,
            data={"attempt": attempts - 1, "html_path": str(repair_path), "report": report},
            metadata=metadata,
        )

    metadata["validation_warnings"] = [warning["message"] for warning in report.get("warnings", [])]
    if not report["ok"]:
        yield agent_error_event(
            run_id=run_id,
            phase=phase,
            code="validation_failed",
            message="HTML 生成结果未通过确定性检查",
            detail=report["summary"],
            metadata=metadata,
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
                "attempts": attempts,
                "repaired": repaired,
                "degraded": metadata["degraded"],
                "validation_warnings": metadata["validation_warnings"],
                "render_mode": plan.get("interactive_type"),
                "subject": plan.get("subject"),
                "plan": plan,
                "artifacts": {
                    "html_path": str(artifacts.html_path),
                    "report_path": str(artifacts.report_path),
                },
            },
        },
        metadata=metadata,
    )
    if metadata["degraded"]:
        yield agent_sse_event(
            "context.compressed",
            run_id=run_id,
            phase=phase,
            data={"context_status": {"status": "compressed", "summary": "大型 HTML 和检查报告已写入沙箱，仅保留摘要。"}},
            metadata=metadata,
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
