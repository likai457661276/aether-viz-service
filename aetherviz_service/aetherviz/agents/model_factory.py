"""LangChain model and Deep Agent factory."""

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


def create_chat_model(kind: str):
    from langchain_openai import ChatOpenAI

    if kind == "planning":
        return ChatOpenAI(
            model=settings.aetherviz_plan_model or settings.planning_openai_model,
            api_key=_blank_to_none(settings.planning_openai_api_key) or _blank_to_none(settings.openai_api_key),
            base_url=_blank_to_none(settings.planning_openai_base_url) or _blank_to_none(settings.openai_base_url),
            temperature=0.3,
            max_tokens=16384,
            reasoning_effort=settings.planning_reasoning_effort or "high",
        )
    return ChatOpenAI(
        model=settings.aetherviz_html_model if kind == "html" else settings.aetherviz_repair_model,
        api_key=_blank_to_none(settings.openai_api_key),
        base_url=_blank_to_none(settings.openai_base_url),
        temperature=0.2 if kind == "html" else 0.08,
        max_tokens=16384,
        extra_body={"enable_thinking": False},
    )


def create_agent_app(kind: str, *, tools: list[Any] | None = None, system_prompt: str = ""):
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=create_chat_model(kind),
        tools=tools or [],
        system_prompt=system_prompt,
        name=f"aetherviz-{kind}-agent",
    )


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
