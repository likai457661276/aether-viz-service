from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI互动实验"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 10095
    log_level: str = "INFO"
    openai_api_key: str | None = None
    openai_base_url: str | None = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_plan_model: str = "deepseek-v4-flash"
    openai_html_model: str = "qwen3.7-plus"
    aetherviz_gsap_cdn_url: str = "https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"
    aetherviz_html_enable_thinking: bool = False
    aetherviz_html_reasoning_effort: str | None = None
    aetherviz_html_max_tokens: int = 12288
    aetherviz_max_repair_attempts: int = 1
    aetherviz_plan_max_tokens: int = 3072
    aetherviz_plan_timeout_seconds: int = 180
    aetherviz_plan_max_retries: int = 1
    aetherviz_html_timeout_seconds: int = 600
    aetherviz_html_max_retries: int = 1
    aetherviz_repair_timeout_seconds: int = 300
    aetherviz_repair_max_retries: int = 1
    langsmith_tracing: bool = False
    langsmith_endpoint: str | None = "https://api.smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None
    langsmith_workspace_id: str | None = None

    @field_validator("aetherviz_gsap_cdn_url")
    @classmethod
    def validate_gsap_cdn_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("AETHERVIZ_GSAP_CDN_URL 必须是有效的 HTTPS URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("AETHERVIZ_GSAP_CDN_URL 不允许包含凭据、query 或 fragment")
        return normalized

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
