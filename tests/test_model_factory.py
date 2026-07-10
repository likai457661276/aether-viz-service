"""Direct chat model factory regression tests."""

from aetherviz_service.aetherviz.agents import model_factory
from aetherviz_service.config import settings


def test_html_model_kwargs_include_timeout_and_limited_retries(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_base_url", "https://example.invalid/v1")
    monkeypatch.setattr(settings, "aetherviz_html_timeout_seconds", 123)
    monkeypatch.setattr(settings, "aetherviz_html_max_retries", 1)

    kwargs = model_factory._html_model_kwargs()

    assert kwargs["timeout"] == 123
    assert kwargs["max_retries"] == 1
    assert kwargs["extra_body"] == {"enable_thinking": False}
