"""Typed application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration; secrets should be injected by the environment."""

    app_name: str = "API Key Gateway"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://gateway:gateway@localhost:5432/gateway"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "development-only-change-me"
    admin_api_key: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for the current process."""

    return Settings()
