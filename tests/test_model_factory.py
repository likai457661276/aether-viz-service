"""Direct chat model factory regression tests."""

from aetherviz_service.aetherviz.agents import model_factory
from aetherviz_service.config import settings


def test_planning_config_reuses_primary_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert model_factory.has_planning_llm_config() is False

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    assert model_factory.has_planning_llm_config() is True


def test_html_model_kwargs_include_timeout_and_limited_retries(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_base_url", "https://example.invalid/v1")
    monkeypatch.setattr(settings, "aetherviz_html_timeout_seconds", 123)
    monkeypatch.setattr(settings, "aetherviz_html_max_retries", 1)
    monkeypatch.setattr(settings, "aetherviz_html_enable_thinking", False)
    monkeypatch.setattr(settings, "openai_html_model", "qwen3.7-plus")
    monkeypatch.setattr(settings, "aetherviz_html_max_tokens", 12288)

    kwargs = model_factory._html_model_kwargs()

    assert kwargs["timeout"] == 123
    assert kwargs["max_retries"] == 1
    assert kwargs["model"] == "qwen3.7-plus"
    assert kwargs["max_tokens"] == 12288
    assert kwargs["extra_body"] == {"enable_thinking": False}


def test_html_model_kwargs_enable_reasoning(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aetherviz_html_enable_thinking", True)
    monkeypatch.setattr(settings, "aetherviz_html_reasoning_effort", "medium")

    kwargs = model_factory._html_model_kwargs()

    assert kwargs["model"] == settings.openai_html_model
    assert kwargs["extra_body"] == {"enable_thinking": True}
    assert kwargs["reasoning_effort"] == "medium"


def test_planning_and_html_models_are_configured_separately(monkeypatch) -> None:
    captured: list[dict] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.append(kwargs)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(settings, "openai_plan_model", "plan-model")
    monkeypatch.setattr(settings, "openai_html_model", "html-model")
    monkeypatch.setattr(settings, "aetherviz_plan_max_tokens", 3072)
    monkeypatch.setattr(settings, "aetherviz_html_max_tokens", 12288)

    model_factory.create_chat_model("planning")
    model_factory.create_chat_model("html")
    model_factory.create_chat_model("edit")
    model_factory.create_chat_model("repair")

    assert [kwargs["model"] for kwargs in captured] == ["plan-model", "html-model", "html-model", "html-model"]
    assert [kwargs["max_tokens"] for kwargs in captured] == [3072, 12288, 12288, 12288]
    assert captured[0]["temperature"] == 0.1
    assert captured[0]["extra_body"] == {"enable_thinking": False}
    assert captured[0]["model_kwargs"] == {"response_format": {"type": "json_object"}}
    assert captured[0]["stream_usage"] is True
    assert "reasoning_effort" not in captured[0]
    assert captured[2]["timeout"] == settings.aetherviz_html_timeout_seconds
    assert captured[2]["extra_body"] == {"enable_thinking": False}
