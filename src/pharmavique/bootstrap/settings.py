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

    # AI providers (ADR-005). Keys only from the environment; model ids are configuration.
    openrouter_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    # The assistant's language model (needs tool calling).
    llm_provider: Literal["groq", "openrouter"] = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    # Embeddings through an OpenAI-compatible endpoint (ADR-006); the column holds 1024 dimensions.
    embedding_base_url: str = "https://openrouter.ai/api/v1"
    embedding_model: str = "baai/bge-m3"
    embedding_dimensions: int = 1024
    # Vision model that reads boxes and prescriptions (through OpenRouter).
    vision_model: str = "google/gemma-4-31b-it:free"
    # Speech (through Groq): Whisper for speech to text, Orpheus Arabic (Saudi) for text to speech.
    stt_model: str = "whisper-large-v3-turbo"
    tts_model: str = "canopylabs/orpheus-arabic-saudi"
    tts_voice: str = ""  # provider default when empty


@lru_cache
def get_settings() -> Settings:
    return Settings()
