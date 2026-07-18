"""Application settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aetherviz_service.config import Settings


def test_html_generation_thinking_disabled_by_default() -> None:
    """HTML 直出阶段默认应关闭推理模式：推理内容不展示给用户，且推理与正文共享
    completion token 预算，开启后实测会显著增加耗时并提高输出被截断的概率。
    """
    settings = Settings(_env_file=None)

    assert settings.openai_plan_model == "deepseek-v4-flash"
    assert settings.openai_html_model == "qwen3.7-plus"
    assert settings.openai_repair_model == "deepseek-v4-flash"
    assert settings.openai_edit_analysis_model == "deepseek-v4-flash"
    assert settings.aetherviz_plan_max_tokens == 3072
    assert settings.aetherviz_edit_analysis_max_tokens == 2048
    assert settings.aetherviz_edit_analysis_timeout_seconds == 30
    assert settings.aetherviz_html_max_tokens == 16384
    assert settings.aetherviz_edit_max_tokens == 16384
    assert settings.aetherviz_edit_temperature == 0.15
    assert settings.aetherviz_repair_max_tokens == 16384
    assert settings.aetherviz_html_enable_thinking is False
    assert settings.aetherviz_html_reasoning_effort is None
    assert settings.aetherviz_edit_enable_thinking is True
    assert settings.aetherviz_edit_reasoning_effort is None


@pytest.mark.parametrize(
    "field",
    ["aetherviz_html_max_tokens", "aetherviz_edit_max_tokens", "aetherviz_repair_max_tokens"],
)
def test_full_html_output_budget_must_cover_hard_limit(field: str) -> None:
    with pytest.raises(ValidationError, match="完整 HTML 输出预算不足"):
        Settings(_env_file=None, **{field: 12_288})


def test_edit_retry_count_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="AETHERVIZ_EDIT_MAX_RETRIES"):
        Settings(_env_file=None, aetherviz_edit_max_retries=-1)


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_edit_temperature_must_be_bounded(value: float) -> None:
    with pytest.raises(ValidationError, match="AETHERVIZ_EDIT_TEMPERATURE"):
        Settings(_env_file=None, aetherviz_edit_temperature=value)


def test_gsap_cdn_url_accepts_https() -> None:
    settings = Settings(
        _env_file=None,
        aetherviz_gsap_cdn_url="https://assets.example.edu/vendor/gsap.min.js",
    )

    assert settings.aetherviz_gsap_cdn_url == "https://assets.example.edu/vendor/gsap.min.js"


def test_katex_cdn_urls_are_fixed_https_resources() -> None:
    settings = Settings(_env_file=None)

    assert settings.aetherviz_katex_enabled is True
    assert settings.aetherviz_katex_css_url.startswith("https://")
    assert settings.aetherviz_katex_js_url.startswith("https://")
    assert "@" in settings.aetherviz_katex_css_url


@pytest.mark.parametrize(
    "url",
    [
        "http://assets.example.edu/vendor/gsap.min.js",
        "javascript:alert(1)",
        "https://user:password@assets.example.edu/gsap.min.js",
        "https://assets.example.edu/gsap.min.js?token=secret",
        "https://assets.example.edu/gsap.min.js#fragment",
    ],
)
def test_gsap_cdn_url_rejects_unsafe_values(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, aetherviz_gsap_cdn_url=url)
