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

    # Folder with the stored product pictures (images/...); only files inside it are served.
    media_dir: str = "data/media"

    # AI providers (ADR-005). Keys only from the environment; model ids are configuration.
    openrouter_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    # The assistant's language model (needs tool calling).
    llm_provider: Literal["groq", "openrouter"] = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    # Prompt-injection classifier (Groq); adds to the rule-based guardrails. Empty disables it.
    prompt_guard_model: str = "meta-llama/llama-prompt-guard-2-86m"
    # Embeddings through an OpenAI-compatible endpoint (ADR-006); the column holds 1024 dimensions.
    embedding_base_url: str = "https://openrouter.ai/api/v1"
    embedding_model: str = "baai/bge-m3"
    embedding_dimensions: int = 1024
    # Vision models that read boxes and prescriptions (through OpenRouter), tried in order: free
    # models are often busy. Measured on a box photo 2026-11-19: nemotron 6 s, ling 42 s.
    vision_models: list[str] = [
        "nvidia/nemotron-3.5-super-vl:free",
        "google/gemma-4-31b-it:free",
        "inclusionai/ling-3.2-flash:free",
    ]
    # Speech to text: Whisper through Groq.
    stt_model: str = "whisper-large-v3-turbo"
    # Text to speech: ElevenLabs by default (owner, 2026-11-19), Groq Orpheus Arabic Saudi as the
    # alternative. Set ELEVENLABS_VOICE_ID to a Saudi voice from the ElevenLabs voice library.
    tts_provider: Literal["elevenlabs", "groq"] = "elevenlabs"
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_model: str = "eleven_v3"
    tts_model: str = "canopylabs/orpheus-arabic-saudi"
    tts_voice: str = "noura"  # Saudi voices: abdullah, fahad, sultan, lulwa, noura, aisha


@lru_cache
def get_settings() -> Settings:
    return Settings()
