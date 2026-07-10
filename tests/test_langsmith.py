"""LangSmith observability tests."""

from __future__ import annotations

import os

from aetherviz_service.config import settings
from aetherviz_service.observability.langsmith import configure_langsmith


def test_configure_langsmith_sets_env(monkeypatch) -> None:
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", "test-langsmith-key")
    monkeypatch.setattr(settings, "langsmith_project", "deepagents-v4-html")
    monkeypatch.setattr(settings, "langsmith_endpoint", "https://api.smith.langchain.com")
    monkeypatch.setattr(settings, "langsmith_workspace_id", None)

    assert configure_langsmith() is True
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "test-langsmith-key"
    assert os.environ["LANGCHAIN_API_KEY"] == "test-langsmith-key"
    assert os.environ["LANGSMITH_PROJECT"] == "deepagents-v4-html"
    assert os.environ["LANGCHAIN_PROJECT"] == "deepagents-v4-html"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"


def test_configure_langsmith_disabled_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "langsmith_tracing", True)
    monkeypatch.setattr(settings, "langsmith_api_key", None)

    assert configure_langsmith() is False


def test_configure_langsmith_disabled_when_flag_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    monkeypatch.setattr(settings, "langsmith_api_key", "test-langsmith-key")

    assert configure_langsmith() is False
