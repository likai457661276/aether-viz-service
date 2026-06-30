from types import SimpleNamespace

import pytest

from markdown_to_html_ppt.llm_service import LLMServiceError, _primary_model_name, _resolve_llm_config


def make_config(**overrides):
    values = {
        "openai_api_key": None,
        "openai_model": "qwen3.7-plus",
        "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_primary_model_name_uses_first_configured_model() -> None:
    assert _primary_model_name(" qwen3.7-plus , qwen-plus ") == "qwen3.7-plus"
    assert _primary_model_name("   ") is None
    assert _primary_model_name(None) is None


def test_resolve_llm_config_uses_openai_compatible_settings() -> None:
    config = make_config(
        openai_api_key="compatible-key",
        openai_model="qwen3.7-plus",
        openai_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    resolved = _resolve_llm_config(config)

    assert resolved.api_key == "compatible-key"
    assert resolved.model == "qwen3.7-plus"
    assert resolved.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_resolve_llm_config_allows_switching_openai_compatible_provider() -> None:
    config = make_config(
        openai_api_key="compatible-key",
        openai_model="gpt-4.1-mini",
        openai_base_url="https://api.openai.com/v1",
    )

    resolved = _resolve_llm_config(config)

    assert resolved.api_key == "compatible-key"
    assert resolved.model == "gpt-4.1-mini"
    assert resolved.base_url == "https://api.openai.com/v1"


def test_resolve_llm_config_requires_a_key() -> None:
    with pytest.raises(LLMServiceError, match="OPENAI_API_KEY"):
        _resolve_llm_config(make_config())
