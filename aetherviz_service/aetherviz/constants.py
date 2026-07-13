"""AetherViz generation constants."""

from aetherviz_service.config import settings

# 仅约束模型生成/修复的业务 HTML，用于平衡生成耗时、上下文和实现复杂度。
MODEL_HTML_TARGET_CHARS = 32000
MODEL_HTML_HARD_LIMIT_CHARS = 40000

# 最终装配 HTML 不参与模型质量判定；该上限只防止重复装配或异常膨胀。
ASSEMBLED_HTML_SAFETY_LIMIT_CHARS = 64000

# 兼容既有导入，语义仍是模型业务 HTML 上限。
HTML_OUTPUT_TARGET_CHARS = MODEL_HTML_TARGET_CHARS
HTML_OUTPUT_HARD_LIMIT_CHARS = MODEL_HTML_HARD_LIMIT_CHARS


def get_gsap_core_cdn_url() -> str:
    return settings.aetherviz_gsap_cdn_url


def get_katex_cdn_urls() -> tuple[str, str]:
    return settings.aetherviz_katex_css_url, settings.aetherviz_katex_js_url


def is_katex_enabled() -> bool:
    return settings.aetherviz_katex_enabled
