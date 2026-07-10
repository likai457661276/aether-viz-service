"""Application settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aetherviz_service.config import Settings


def test_gsap_cdn_url_accepts_https() -> None:
    settings = Settings(
        _env_file=None,
        aetherviz_gsap_cdn_url="https://assets.example.edu/vendor/gsap.min.js",
    )

    assert settings.aetherviz_gsap_cdn_url == "https://assets.example.edu/vendor/gsap.min.js"


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
