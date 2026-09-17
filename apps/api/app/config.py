from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "闲鱼 AI 智能客服"
    database_url: str = "sqlite+aiosqlite:///./xianyu_dev.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-only-change-me"
    cors_origins: str = "http://localhost:3000"
    jwt_expire_minutes: int = 1440
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 800
    debounce_ms: int = 1500
    history_limit: int = 16
    # embedded is convenient for local development and tests. Docker runs the
    # API and the platform listener as separate processes.
    xianyu_runtime_mode: str = "embedded"
    xianyu_command_timeout_seconds: int = 30
    xianyu_event_max_attempts: int = 5
    xianyu_event_retry_base_seconds: float = 1.0
    xianyu_event_retry_max_seconds: float = 60.0
    xianyu_event_claim_idle_ms: int = 1_000
    delivery_lease_seconds: int = 90
    delivery_reconcile_interval_seconds: int = 15

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
