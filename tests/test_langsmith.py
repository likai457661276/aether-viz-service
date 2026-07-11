"""LangSmith observability tests."""

from __future__ import annotations

import os

from aetherviz_service.aetherviz.api.sse import agent_sse_event
from aetherviz_service.aetherviz.workflow.generate_workflow import _summarize_sse_trace
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
