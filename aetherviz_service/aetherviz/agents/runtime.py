"""Phase dispatcher for AetherViz Deep Agents workflows."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from aetherviz_service.aetherviz.api.sse import agent_error_event
from aetherviz_service.aetherviz.sandbox.manager import SandboxManager
from aetherviz_service.aetherviz.workflow.edit_html_workflow import run_edit_html_workflow
from aetherviz_service.aetherviz.workflow.generate_workflow import run_generate_workflow
from aetherviz_service.aetherviz.workflow.plan_workflow import run_approve_plan_workflow, run_plan_workflow
from aetherviz_service.aetherviz.workflow.revise_plan_workflow import run_revise_plan_workflow

logger = logging.getLogger(__name__)


def agent_runtime_stream(
    *,
    phase: str,
    topic: str = "",
    current_plan: dict[str, Any] | None = None,
    message: str | None = None,
    plan: dict[str, Any] | None = None,
    approved_plan: dict[str, Any] | None = None,
    current_html: str | None = None,
    context: dict[str, Any] | None = None,
) -> Iterator[str]:
    sandbox = SandboxManager()
    artifacts = sandbox.create_run()
    run_id = artifacts.run_id
    try:
        if phase == "plan":
            yield from run_plan_workflow(run_id=run_id, topic=topic, context=context)
            return
        if phase == "revise_plan":
            yield from run_revise_plan_workflow(
                run_id=run_id,
                topic=topic,
                current_plan=current_plan or {},
                message=message or "",
                context=context,
            )
            return
        if phase == "approve_plan":
            yield from run_approve_plan_workflow(run_id=run_id, plan=plan or {})
            return
        if phase == "generate":
            yield from run_generate_workflow(
                run_id=run_id,
                topic=topic or str((approved_plan or {}).get("title") or "AI互动实验"),
                approved_plan=approved_plan or {},
                sandbox=sandbox,
                artifacts=artifacts,
            )
            return
        if phase == "edit_html":
            yield from run_edit_html_workflow(
                run_id=run_id,
                current_html=current_html or "",
                message=message or "",
                context=context,
                sandbox=sandbox,
                artifacts=artifacts,
            )
            return
        yield agent_error_event(run_id=run_id, phase=phase, code="invalid_phase", message=f"不支持的 phase：{phase}")
    except Exception as exc:
        logger.exception("AetherViz agent runtime failed")
        yield agent_error_event(
            run_id=run_id,
            phase=phase,
            code="runtime_error",
            message="Agent 工作流执行失败",
            detail=str(exc),
        )
