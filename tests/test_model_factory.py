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

    kwargs = model_factory._html_model_kwargs()

    assert kwargs["timeout"] == 123
    assert kwargs["max_retries"] == 1
    assert kwargs["extra_body"] == {"enable_thinking": False}


def test_html_model_kwargs_enable_reasoning(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aetherviz_html_enable_thinking", True)
    monkeypatch.setattr(settings, "aetherviz_html_reasoning_effort", "medium")

    kwargs = model_factory._html_model_kwargs()

    assert kwargs["model"] == settings.openai_model
    assert kwargs["extra_body"] == {"enable_thinking": True}
    assert kwargs["reasoning_effort"] == "medium"
