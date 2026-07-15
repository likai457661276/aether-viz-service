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
    return has_primary_llm_config()


def _html_model_kwargs(*, max_tokens: int | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": settings.openai_html_model,
        "api_key": _blank_to_none(settings.openai_api_key),
        "base_url": _blank_to_none(settings.openai_base_url),
        "temperature": 0.2,
        "max_tokens": max(
            settings.aetherviz_html_max_tokens if max_tokens is None else max_tokens,
            512,
        ),
        "timeout": max(settings.aetherviz_html_timeout_seconds, 1),
        "max_retries": max(settings.aetherviz_html_max_retries, 0),
        "stream_usage": True,
    }
    if settings.aetherviz_html_enable_thinking:
        kwargs["extra_body"] = {"enable_thinking": True}
        reasoning_effort = _blank_to_none(settings.aetherviz_html_reasoning_effort)
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
    else:
        kwargs["extra_body"] = {"enable_thinking": False}
    return kwargs


def create_chat_model(kind: str, *, response_schema: dict[str, Any] | None = None):
    from langchain_openai import ChatOpenAI

    if kind == "planning":
        planning_kwargs: dict[str, Any] = {
            "model": settings.openai_plan_model,
            "api_key": _blank_to_none(settings.openai_api_key),
            "base_url": _blank_to_none(settings.openai_base_url),
            "temperature": 0.1,
            "max_tokens": max(settings.aetherviz_plan_max_tokens, 512),
            "timeout": max(settings.aetherviz_plan_timeout_seconds, 1),
            "max_retries": max(settings.aetherviz_plan_max_retries, 0),
            "extra_body": {"enable_thinking": False},
            "model_kwargs": {"response_format": {"type": "json_object"}},
            "stream_usage": True,
        }
        return ChatOpenAI(**planning_kwargs)
    if kind == "html":
        return ChatOpenAI(**_html_model_kwargs())
    if kind == "scene":
        kwargs = _html_model_kwargs(max_tokens=settings.aetherviz_scene_max_tokens)
        kwargs["temperature"] = 0.0
        kwargs["extra_body"] = {"enable_thinking": False}
        kwargs["model_kwargs"] = {
            "response_format": (
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "aetherviz_geometry_ir",
                        "strict": True,
                        "schema": response_schema,
                    },
                }
                if response_schema
                else {"type": "json_object"}
            )
        }
        kwargs.pop("reasoning_effort", None)
        return ChatOpenAI(**kwargs)
    if kind == "edit":
        kwargs = _html_model_kwargs(max_tokens=settings.aetherviz_edit_max_tokens)
        kwargs["temperature"] = 0.08
        kwargs["extra_body"] = {"enable_thinking": False}
        kwargs.pop("reasoning_effort", None)
        return ChatOpenAI(**kwargs)
    if kind == "edit_patch":
        kwargs = _html_model_kwargs(max_tokens=settings.aetherviz_edit_patch_max_tokens)
        kwargs["temperature"] = 0.0
        kwargs["extra_body"] = {"enable_thinking": False}
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        kwargs.pop("reasoning_effort", None)
        return ChatOpenAI(**kwargs)
    return ChatOpenAI(
        model=settings.openai_html_model,
        api_key=_blank_to_none(settings.openai_api_key),
        base_url=_blank_to_none(settings.openai_base_url),
        temperature=0.08,
        max_tokens=max(settings.aetherviz_repair_max_tokens, 512),
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


def extract_llm_usage(message: Any) -> tuple[int | None, int | None]:
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict) and isinstance(message, dict):
        usage = message.get("usage_metadata")
    if not isinstance(usage, dict):
        return None, None
    return _positive_int(usage.get("input_tokens")), _positive_int(usage.get("output_tokens"))


def _positive_int(value: Any) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None
