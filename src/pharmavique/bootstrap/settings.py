"""Environment-driven configuration. Secrets come from the environment only, never from code."""

from functools import lru_cache
from typing import Any, Literal

from pydantic import SecretStr, field_validator
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
    # Signs access tokens (at least 32 random characters). Without it accounts answer 503.
    jwt_secret: SecretStr | None = None

    # Browser origins allowed to call the API (the app's web build). JSON list in the environment,
    # for example PHARMAVIQUE_CORS_ORIGINS='["http://localhost:8081"]'. Native apps need none.
    cors_origins: list[str] = ["http://localhost:8081", "http://127.0.0.1:8081"]

    # Requests per minute per client address; 0 turns a limit off. The heavy limit covers the
    # endpoints that cost money or CPU (assistant, voice, scan).
    rate_limit_per_minute: int = 300
    heavy_rate_limit_per_minute: int = 30
    # How many reverse proxies of ours sit in front of the API; 0 = none (use the socket address).
    # With 1, the last X-Forwarded-For entry is the caller's address, as our balancer wrote it.
    trusted_proxy_hops: int = 0

    # Shared read cache (needs PHARMAVIQUE_REDIS_URL). Entries also expire on their own.
    cache_ttl_seconds: int = 600
    # Database connections per API process; with many instances put PgBouncer in front.
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Background jobs for slow work (scan, assistant). "inline" runs them inside the API process
    # (no worker to start); "arq" hands them to `pharmavique worker` processes through Redis,
    # which is what a large deployment runs, scaled by the number of workers.
    job_backend: Literal["inline", "arq"] = "inline"
    job_max_concurrency: int = 8  # jobs one worker runs at once (the model providers' limits apply)
    job_timeout_seconds: int = 90
    jobs_per_user_per_minute: int = 6  # submissions per caller; 0 turns the limit off
    job_max_queue_depth: int = 500  # new jobs are refused (503) while this many are waiting

    # Folder with the stored product pictures (images/...); only files inside it are served.
    media_dir: str = "data/media"
    # Folder the daily refresh writes its summaries to; the operator board reads it (read-only).
    refresh_dir: str = "data/refresh"

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

    @field_validator(
        "database_url",
        "redis_url",
        "jwt_secret",
        "openrouter_api_key",
        "groq_api_key",
        "elevenlabs_api_key",
        mode="before",
    )
    @classmethod
    def _empty_means_unset(cls, value: Any) -> Any:
        """`PHARMAVIQUE_REDIS_URL=` (set but empty) is the same as not setting it."""
        return None if isinstance(value, str) and not value.strip() else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
