"""LangSmith observability tests."""

from __future__ import annotations

import os

from aetherviz_service.aetherviz.agents.planner_agent import (
    PlanningStreamResult,
    _summarize_planning_trace,
)
from aetherviz_service.aetherviz.agents.runtime import _summarize_runtime_sse
from aetherviz_service.aetherviz.api.sse import (
    agent_sse_event,
    register_langsmith_trace_id,
    unregister_langsmith_trace_id,
)
from aetherviz_service.aetherviz.contracts.pipeline import _summarize_sse_trace
from aetherviz_service.config import settings
from aetherviz_service.observability.langsmith import configure_langsmith


def test_configure_langsmith_sets_env(monkeypatch) -> None:
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "test-langsmith-key")
    monkeypatch.setattr(settings, "langsmith_project", "aetherviz-direct-html")
    monkeypatch.setattr(settings, "langsmith_endpoint", "https://api.smith.langchain.com")
    monkeypatch.setattr(settings, "langsmith_workspace_id", None)

    assert configure_langsmith() is True
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "test-langsmith-key"
    assert os.environ["LANGCHAIN_API_KEY"] == "test-langsmith-key"
    assert os.environ["LANGSMITH_PROJECT"] == "aetherviz-direct-html"
    assert os.environ["LANGCHAIN_PROJECT"] == "aetherviz-direct-html"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"


def test_configure_langsmith_disabled_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", None)

    assert configure_langsmith() is False


def test_configure_langsmith_disabled_when_flag_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    monkeypatch.setattr(settings, "langsmith_api_key", "test-langsmith-key")

    assert configure_langsmith() is False


def test_generate_trace_summary_excludes_complete_html() -> None:
    chunk = agent_sse_event(
        "html.done",
        run_id="run_trace",
        phase="generate",
        data={
            "html": "<!DOCTYPE html><html><body>private output</body></html>",
            "metadata": {"chars": 58, "bytes": 58, "repaired": True},
        },
    )

    summary = _summarize_sse_trace([chunk])

    assert summary["events"] == ["html.done"]
    assert summary["final"] == {"event": "html.done", "chars": 58, "bytes": 58, "repaired": True}
    assert "private output" not in str(summary)


def test_request_trace_summary_marks_sse_error_outcome() -> None:
    chunk = agent_sse_event(
        "error",
        run_id="run_trace",
        phase="edit_html",
        data={"code": "edit_local_patch_rejected", "message": "局部补丁失败"},
    )

    summary = _summarize_runtime_sse([chunk])

    assert summary == {
        "sse_event_count": 1,
        "outcome": "error",
        "completed": False,
        "error_code": "edit_local_patch_rejected",
    }


def test_sse_event_includes_current_langsmith_trace_id() -> None:
    register_langsmith_trace_id("run_trace", "4de5cd2f-d9d0-49f8-97bf-bff2395c8201")
    try:
        event = agent_sse_event("plan.started", run_id="run_trace", phase="plan")
    finally:
        unregister_langsmith_trace_id("run_trace")

    assert '"langsmith_trace_id": "4de5cd2f-d9d0-49f8-97bf-bff2395c8201"' in event


def test_planning_trace_summary_includes_normalized_plan() -> None:
    plan = {
        "plan_id": "plan_trace",
        "topic": "圆周率",
        "interactive_type": "simulation",
        "subject": "math",
    }

    summary = _summarize_planning_trace(
        [PlanningStreamResult(plan=plan, degraded=False, total_tokens=321)]
    )

    assert summary["completed"] is True
    assert summary["plan"] == plan
    assert summary["token_usage"]["total_tokens"] == 321
