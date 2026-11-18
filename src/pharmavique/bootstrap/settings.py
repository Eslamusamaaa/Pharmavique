"""Environment-driven configuration. Secrets come from the environment only, never from code."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PHARMAVIQUE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Not used by the Phase 0 skeleton; wired in Phase 1. SecretStr keeps them out of repr/logs.
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None

    # Browser origins allowed to call the API (the app's web build). JSON list in the environment,
    # for example PHARMAVIQUE_CORS_ORIGINS='["http://localhost:8081"]'. Native apps need none.
    cors_origins: list[str] = ["http://localhost:8081", "http://127.0.0.1:8081"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
