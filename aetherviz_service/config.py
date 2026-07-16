from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aetherviz_service.aetherviz.limits import MIN_FULL_HTML_OUTPUT_TOKENS
from aetherviz_service.aetherviz.tools.external_url import normalize_allowed_external_url


class Settings(BaseSettings):
    app_name: str = "AI教学动画"
    openai_api_key: str | None = None
    openai_base_url: str | None = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_plan_model: str = "deepseek-v4-flash"
    openai_html_model: str = "qwen3.7-plus"
    openai_repair_model: str = "deepseek-v4-flash"
    aetherviz_gsap_cdn_url: str = "https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"
    aetherviz_katex_enabled: bool = True
    aetherviz_katex_css_url: str = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css"
    aetherviz_katex_js_url: str = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"
    aetherviz_html_enable_thinking: bool = False
    aetherviz_html_reasoning_effort: str | None = None
    aetherviz_edit_enable_thinking: bool = True
    aetherviz_edit_reasoning_effort: str | None = None
    aetherviz_html_max_tokens: int = 16384
    aetherviz_scene_max_tokens: int = 12288
    aetherviz_edit_max_tokens: int = 16384
    aetherviz_repair_max_tokens: int = 16384
    aetherviz_max_repair_attempts: int = 1
    aetherviz_plan_max_tokens: int = 3072
    aetherviz_plan_timeout_seconds: int = 180
    aetherviz_plan_max_retries: int = 1
    aetherviz_html_timeout_seconds: int = 600
    aetherviz_html_max_retries: int = 1
    aetherviz_html_stream_max_retries: int = 1
    aetherviz_repair_timeout_seconds: int = 300
    aetherviz_repair_max_retries: int = 1
    langsmith_tracing: bool = False
    langsmith_endpoint: str | None = "https://api.smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None
    langsmith_workspace_id: str | None = None

    @field_validator(
        "aetherviz_gsap_cdn_url",
        "aetherviz_katex_css_url",
        "aetherviz_katex_js_url",
    )
    @classmethod
    def validate_cdn_url(cls, value: str) -> str:
        try:
            return normalize_allowed_external_url(value)
        except ValueError as exc:
            raise ValueError("AetherViz CDN 地址必须是无凭据、query、fragment 的有效 HTTPS URL") from exc

    @model_validator(mode="after")
    def validate_full_html_output_budgets(self) -> "Settings":
        if self.aetherviz_max_repair_attempts < 0:
            raise ValueError("AETHERVIZ_MAX_REPAIR_ATTEMPTS 不能小于 0")
        undersized = {
            name: value
            for name, value in {
                "AETHERVIZ_HTML_MAX_TOKENS": self.aetherviz_html_max_tokens,
                "AETHERVIZ_EDIT_MAX_TOKENS": self.aetherviz_edit_max_tokens,
                "AETHERVIZ_REPAIR_MAX_TOKENS": self.aetherviz_repair_max_tokens,
            }.items()
            if value < MIN_FULL_HTML_OUTPUT_TOKENS
        }
        if undersized:
            configured = ", ".join(f"{name}={value}" for name, value in undersized.items())
            raise ValueError(
                "完整 HTML 输出预算不足："
                f"{configured}；每项至少需要 {MIN_FULL_HTML_OUTPUT_TOKENS} token，建议配置为 16384"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
