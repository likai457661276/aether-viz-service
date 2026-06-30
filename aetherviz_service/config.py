from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI互动实验"
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 10095
    log_level: str = "INFO"
    openai_api_key: str | None = None
    openai_base_url: str | None = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openai_model: str = "qwen3.7-plus"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
