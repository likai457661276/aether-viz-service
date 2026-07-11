"""Security allowlist for generated AetherViz HTML."""

from __future__ import annotations

from aetherviz_service.aetherviz.constants import get_gsap_core_cdn_url, get_katex_cdn_urls
from aetherviz_service.config import settings


def allowed_external_urls() -> set[str]:
    urls = {get_gsap_core_cdn_url()}
    if settings.aetherviz_katex_enabled:
        urls.update(get_katex_cdn_urls())
    return urls
