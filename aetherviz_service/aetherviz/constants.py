"""AetherViz generation constants."""

from aetherviz_service.config import settings

# 为服务端布局骨架和确定性运行时 guard 预留最终输出空间。
HTML_OUTPUT_TARGET_CHARS = 32000
HTML_OUTPUT_HARD_LIMIT_CHARS = 40000


def get_gsap_core_cdn_url() -> str:
    return settings.aetherviz_gsap_cdn_url


def get_katex_cdn_urls() -> tuple[str, str]:
    return settings.aetherviz_katex_css_url, settings.aetherviz_katex_js_url


def is_katex_enabled() -> bool:
    return settings.aetherviz_katex_enabled
