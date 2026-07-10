"""LangSmith tracing setup for LangChain model calls."""

from __future__ import annotations

import logging
import os

from aetherviz_service.config import settings

logger = logging.getLogger(__name__)


def _set_env(name: str, value: str) -> None:
    os.environ[name] = value


def configure_langsmith() -> bool:
    """Sync LangSmith settings into process env for LangChain auto-tracing."""
    if not settings.langsmith_tracing:
        return False

    api_key = (settings.langsmith_api_key or "").strip()
    if not api_key:
        logger.warning("LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is empty; tracing disabled")
        return False

    _set_env("LANGSMITH_TRACING", "true")
    _set_env("LANGCHAIN_TRACING_V2", "true")
    _set_env("LANGSMITH_API_KEY", api_key)
    _set_env("LANGCHAIN_API_KEY", api_key)

    endpoint = (settings.langsmith_endpoint or "").strip()
    if endpoint:
        _set_env("LANGSMITH_ENDPOINT", endpoint)
        _set_env("LANGCHAIN_ENDPOINT", endpoint)

    project = (settings.langsmith_project or "").strip()
    if project:
        _set_env("LANGSMITH_PROJECT", project)
        _set_env("LANGCHAIN_PROJECT", project)

    workspace_id = (settings.langsmith_workspace_id or "").strip()
    if workspace_id:
        _set_env("LANGSMITH_WORKSPACE_ID", workspace_id)

    logger.info(
        "LangSmith tracing enabled (project=%s, endpoint=%s)",
        project or "default",
        endpoint or "https://api.smith.langchain.com",
    )
    return True
