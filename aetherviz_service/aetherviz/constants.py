"""AetherViz generation constants."""

from aetherviz_service.aetherviz import limits as _limits
from aetherviz_service.config import settings

MODEL_HTML_TARGET_CHARS = _limits.MODEL_HTML_TARGET_CHARS
MODEL_HTML_HARD_LIMIT_CHARS = _limits.MODEL_HTML_HARD_LIMIT_CHARS
ASSEMBLED_HTML_SAFETY_LIMIT_CHARS = _limits.ASSEMBLED_HTML_SAFETY_LIMIT_CHARS

# 兼容既有导入，语义仍是模型业务 HTML 上限。
HTML_OUTPUT_TARGET_CHARS = MODEL_HTML_TARGET_CHARS
HTML_OUTPUT_HARD_LIMIT_CHARS = MODEL_HTML_HARD_LIMIT_CHARS


def get_gsap_core_cdn_url() -> str:
    return settings.aetherviz_gsap_cdn_url


def get_katex_cdn_urls() -> tuple[str, str]:
    return settings.aetherviz_katex_css_url, settings.aetherviz_katex_js_url


def is_katex_enabled() -> bool:
    return settings.aetherviz_katex_enabled
