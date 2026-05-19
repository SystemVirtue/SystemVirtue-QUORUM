from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str | None = None
    database_url: str = "sqlite+aiosqlite:///./systemvirtue.db"
    redis_url: str = "redis://localhost:6379/0"
    default_quorum_mode: str = "balanced"
    default_hub_model: str = "qwen/qwen2.5-72b-instruct:free"
    allow_paid_models: bool = False
    byok_encryption_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    request_timeout_seconds: float = 30.0


settings = Settings()
