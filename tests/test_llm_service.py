from types import SimpleNamespace

import pytest

import aetherviz_service.llm_service as llm_module
from aetherviz_service.llm_service import LLMServiceError, LLMStreamChunk, _primary_model_name, _resolve_llm_config


def make_config(**overrides):
    values = {
        "openai_api_key": None,
        "openai_model": "qwen3.7-plus",
        "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "planning_openai_api_key": None,
        "planning_openai_model": "deepseek-v4-flash",
        "planning_openai_base_url": None,
        "planning_reasoning_effort": "high",
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


def test_resolve_llm_config_uses_planning_model_with_shared_key() -> None:
    resolved = _resolve_llm_config(
        make_config(openai_api_key="compatible-key"),
        use_planning_model=True,
    )

    assert resolved.api_key == "compatible-key"
    assert resolved.model == "deepseek-v4-flash"
    assert resolved.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert resolved.reasoning_effort == "high"


def test_resolve_llm_config_allows_dedicated_planning_provider() -> None:
    resolved = _resolve_llm_config(
        make_config(
            openai_api_key="html-key",
            planning_openai_api_key="planning-key",
            planning_openai_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            planning_openai_model="deepseek-v4-flash,deepseek-v4-pro",
            planning_reasoning_effort="max",
        ),
        use_planning_model=True,
    )

    assert resolved.api_key == "planning-key"
    assert resolved.model == "deepseek-v4-flash"
    assert resolved.base_url == "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    assert resolved.reasoning_effort == "max"


def test_call_llm_stream_does_not_enable_thinking_by_default(monkeypatch) -> None:
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="不应转发的推理", content="最终回复")
                        )
                    ]
                ),
                SimpleNamespace(choices=[]),
            ]

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    fake_config = llm_module.ActiveLLMConfig(
        api_key="compatible-key",
        model="qwen3.7-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(llm_module, "_openai_client", lambda **kwargs: (fake_client, fake_config))

    chunks = list(llm_module.call_llm_stream("题目", system_prompt="系统"))

    assert "extra_body" not in calls[0]
    assert chunks == [LLMStreamChunk(kind="content", delta="最终回复")]


def test_call_llm_stream_enables_dashscope_thinking_when_requested(monkeypatch) -> None:
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="先分析数学关系", content="")
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="", content="最终回复")
                        )
                    ]
                ),
                SimpleNamespace(choices=[]),
            ]

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    fake_config = llm_module.ActiveLLMConfig(
        api_key="compatible-key",
        model="qwen3.7-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(llm_module, "_openai_client", lambda **kwargs: (fake_client, fake_config))

    chunks = list(llm_module.call_llm_stream("题目", system_prompt="系统", enable_thinking=True))

    assert calls[0]["extra_body"] == {"enable_thinking": True}
    assert chunks == [
        LLMStreamChunk(kind="reasoning", delta="先分析数学关系"),
        LLMStreamChunk(kind="content", delta="最终回复"),
    ]


def test_call_llm_stream_uses_deepseek_reasoning_effort(monkeypatch) -> None:
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="先推理方案结构", content="")
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="", content="最终方案")
                        )
                    ]
                ),
            ]

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    fake_config = llm_module.ActiveLLMConfig(
        api_key="compatible-key",
        model="deepseek-v4-flash",
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        reasoning_effort="high",
    )
    monkeypatch.setattr(llm_module, "_openai_client", lambda **kwargs: (fake_client, fake_config))

    chunks = list(llm_module.call_planning_llm_stream("题目", system_prompt="系统"))

    assert calls[0]["reasoning_effort"] == "high"
    assert "extra_body" not in calls[0]
    assert chunks == [
        LLMStreamChunk(kind="reasoning", delta="先推理方案结构"),
        LLMStreamChunk(kind="content", delta="最终方案"),
    ]


def test_call_llm_stream_does_not_send_thinking_to_non_dashscope_provider(monkeypatch) -> None:
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(reasoning_content="", content="hello")
                        )
                    ]
                )
            ]

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    fake_config = llm_module.ActiveLLMConfig(
        api_key="compatible-key",
        model="gpt-4.1-mini",
        base_url="https://api.openai.com/v1",
    )
    monkeypatch.setattr(llm_module, "_openai_client", lambda **kwargs: (fake_client, fake_config))

    chunks = list(llm_module.call_llm_stream("题目", system_prompt="系统"))

    assert "extra_body" not in calls[0]
    assert chunks == [LLMStreamChunk(kind="content", delta="hello")]
