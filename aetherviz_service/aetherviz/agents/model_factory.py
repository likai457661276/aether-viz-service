"""LangChain chat model factory for AetherViz workflows."""

from __future__ import annotations

from typing import Any

from aetherviz_service.config import settings

def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def has_primary_llm_config() -> bool:
    return bool(_blank_to_none(settings.openai_api_key))


def has_planning_llm_config() -> bool:
    return bool(_blank_to_none(settings.planning_openai_api_key) or _blank_to_none(settings.openai_api_key))


def _html_model_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": settings.aetherviz_html_model,
        "api_key": _blank_to_none(settings.openai_api_key),
        "base_url": _blank_to_none(settings.openai_base_url),
        "temperature": 0.2,
        "max_tokens": 16384,
        "timeout": max(settings.aetherviz_html_timeout_seconds, 1),
        "max_retries": max(settings.aetherviz_html_max_retries, 0),
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
            "timeout": max(settings.aetherviz_plan_timeout_seconds, 1),
            "max_retries": max(settings.aetherviz_plan_max_retries, 0),
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
        timeout=max(settings.aetherviz_repair_timeout_seconds, 1),
        max_retries=max(settings.aetherviz_repair_max_retries, 0),
        extra_body={"enable_thinking": False},
    )


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
