"""LangChain model and Deep Agent factory."""

from __future__ import annotations

from typing import Any

from aetherviz_service.config import settings

_AETHERVIZ_HARNESS_READY = False

_KIND_TOOL_EXCLUSIONS: dict[str, frozenset[str]] = {
    "html": frozenset({"write_todos", "execute", "task", "read_file", "edit_file", "glob", "grep", "ls"}),
    "repair": frozenset({"write_todos", "execute", "task", "glob", "grep", "ls"}),
}


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def has_primary_llm_config() -> bool:
    return bool(_blank_to_none(settings.openai_api_key))


def has_planning_llm_config() -> bool:
    return bool(_blank_to_none(settings.planning_openai_api_key) or _blank_to_none(settings.openai_api_key))


def _ensure_aetherviz_harness() -> None:
    global _AETHERVIZ_HARNESS_READY
    if _AETHERVIZ_HARNESS_READY:
        return
    from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
    from langchain.agents.middleware import TodoListMiddleware

    register_harness_profile(
        "openai",
        HarnessProfile(
            excluded_middleware=frozenset({TodoListMiddleware, "TodoListMiddleware"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
    _AETHERVIZ_HARNESS_READY = True


def _html_model_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": settings.aetherviz_html_model,
        "api_key": _blank_to_none(settings.openai_api_key),
        "base_url": _blank_to_none(settings.openai_base_url),
        "temperature": 0.2,
        "max_tokens": 16384,
    }
    if settings.aetherviz_html_enable_thinking:
        kwargs["extra_body"] = {"enable_thinking": True}
        reasoning_effort = _blank_to_none(settings.aetherviz_html_reasoning_effort)
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
    else:
        kwargs["extra_body"] = {"enable_thinking": False}
    return kwargs


def create_chat_model(kind: str):
    from langchain_openai import ChatOpenAI

    if kind == "planning":
        planning_kwargs: dict[str, Any] = {
            "model": settings.aetherviz_plan_model or settings.planning_openai_model,
            "api_key": _blank_to_none(settings.planning_openai_api_key) or _blank_to_none(settings.openai_api_key),
            "base_url": _blank_to_none(settings.planning_openai_base_url) or _blank_to_none(settings.openai_base_url),
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        reasoning_effort = _blank_to_none(settings.planning_reasoning_effort)
        if reasoning_effort:
            planning_kwargs["reasoning_effort"] = reasoning_effort
            base_url = str(planning_kwargs.get("base_url") or "").lower()
            if "dashscope" in base_url or "maas.aliyuncs.com" in base_url:
                planning_kwargs["extra_body"] = {"enable_thinking": True}
        return ChatOpenAI(**planning_kwargs)
    if kind == "html":
        return ChatOpenAI(**_html_model_kwargs())
    return ChatOpenAI(
        model=settings.aetherviz_repair_model,
        api_key=_blank_to_none(settings.openai_api_key),
        base_url=_blank_to_none(settings.openai_base_url),
        temperature=0.08,
        max_tokens=16384,
        extra_body={"enable_thinking": False},
    )


def create_agent_app(
    kind: str,
    *,
    tools: list[Any] | None = None,
    system_prompt: str = "",
    permissions: list[Any] | None = None,
):
    from deepagents import create_deep_agent
    from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware
    from deepagents.middleware.filesystem import FilesystemPermission

    _ensure_aetherviz_harness()
    exclusions = _KIND_TOOL_EXCLUSIONS.get(kind, frozenset({"write_todos", "execute", "task"}))
    middleware = [_ToolExclusionMiddleware(excluded=exclusions)]
    if kind == "html" and permissions is None:
        permissions = [FilesystemPermission(operations=["read"], paths=["/**"], mode="deny")]

    kwargs: dict[str, Any] = {
        "model": create_chat_model(kind),
        "tools": tools or [],
        "system_prompt": system_prompt,
        "middleware": middleware,
        "name": f"aetherviz-{kind}-agent",
    }
    if permissions is not None:
        kwargs["permissions"] = permissions
    return create_deep_agent(**kwargs)


def agent_invoke_config(kind: str) -> dict[str, Any]:
    if kind == "html":
        return {"recursion_limit": settings.aetherviz_html_recursion_limit}
    if kind == "repair":
        return {"recursion_limit": settings.aetherviz_repair_recursion_limit}
    return {"recursion_limit": 25}


def extract_llm_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content or "")


def extract_llm_reasoning(message: Any) -> str:
    kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(kwargs, dict) and isinstance(message, dict):
        kwargs = message.get("additional_kwargs")
    if not isinstance(kwargs, dict):
        return ""
    for key in ("reasoning_content", "reasoning"):
        value = kwargs.get(key)
        if value:
            return str(value)
    return ""


def extract_agent_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content:
                return str(content)
            if isinstance(last, dict):
                return str(last.get("content") or "")
        for key in ("content", "output", "text"):
            if result.get(key):
                return str(result[key])
    return str(result or "")
