"""Environment-driven configuration. Secrets come from the environment only, never from code."""

import logging
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pharmavique.foundation.db.url import to_asyncpg_url

MIN_JWT_SECRET_LENGTH = 32


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
    # Signs access tokens (at least 32 random characters). Production refuses to start without it;
    # elsewhere accounts answer 503.
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

    # The pharmacist's shelf scan (many boxes in one photo). On: every box still needs the
    # pharmacist's confirmation and shows its match score. Its accuracy on real shelf photos is
    # unmeasured (Q-32, see docs/SCAN_EVALUATION.md); set to false to switch it off.
    shelf_scan_enabled: bool = True
    # How well the best registry name must match a name read from a photo for the line to count as
    # "confident"; below it the app asks the person to confirm or retake the photo. Untuned on real
    # photos (docs/SCAN_EVALUATION.md); 0 to 1.
    scan_min_score: float = Field(default=0.9, ge=0.0, le=1.0)

    # Email (verification codes, notification digests). "console" prints messages instead of
    # sending them and is for development only; "smtp" sends through any provider that offers SMTP.
    email_backend: Literal["console", "smtp"] = "console"
    email_from: str = "Pharmavique <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    # The address people reach the API at, used for links in emails (the unsubscribe link).
    public_url: str = ""

    # Folder with the stored product pictures (images/...); only files inside it are served.
    media_dir: str = "data/media"
    # Public address of a bucket that holds the same pictures (`products/SA/...`); when set, the
    # picture endpoint redirects there instead of reading the media folder.
    picture_base_url: str | None = None
    # Folder the daily refresh writes its summaries to; the operator board reads it (read-only).
    refresh_dir: str = "data/refresh"

    # AI providers (ADR-005). Keys only from the environment; model ids are configuration.
    openrouter_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    # Web search for medicines the registry does not know (ADR-017); without a key the tool is off.
    tavily_api_key: SecretStr | None = None
    # Ask SFDA's own drug list (sfda.gov.sa) before saying a drug is not in it. No key needed.
    sfda_site_check: bool = True
    # The exported website (`mobile/dist`, from `expo export -p web`), served by the API at `/`.
    web_dir: str | None = None
    # Cloudflare Workers AI (free 10,000 Neurons a day, shared by every model): the assistant's
    # backup model and others. Both values are needed; without them nothing changes.
    cloudflare_api_token: SecretStr | None = None
    cloudflare_account_id: str | None = None
    # The assistant's language model (needs tool calling).
    llm_provider: Literal["groq", "openrouter"] = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    # Groq's second model, tried right after the first. Groq's free plan allows 8,000 tokens a
    # minute per model (the response headers say so for both) and one question takes 10,000 to
    # 16,000, so the first model is often rate limited; this one has its own 8,000 and answers in
    # about a second a call, where the Cloudflare backup took 5 to 29 s a call (measured
    # 2026-11-25). Empty: none.
    groq_backup_model: str = "openai/gpt-oss-20b"
    # The assistant's backup on Cloudflare Workers AI, used when the first model is rate limited or
    # slow. Measured on four real questions (2026-11-22): Gemma 4 answered all four correctly with
    # citations (31 to 42 s each); gpt-oss-120b there answered one of four (the rest came back
    # empty); Llama 4 Scout wrote tool calls as text and answered in English.
    cloudflare_llm_model: str = "@cf/google/gemma-4-26b-a4b-it"
    # Gemma 4 thinks before it answers: about 1,800 characters of hidden reasoning for a three
    # sentence answer, 11.7 s; with thinking off the same answer took 2.5 s (2026-11-25).
    cloudflare_llm_thinking: bool = False
    # The next backups, free models on OpenRouter with tool calling, tried in order after
    # Cloudflare. Measured 2026-11-24 on an Arabic question with a search tool: Nemotron 3 Ultra
    # called it with "بنادول" in 5 s; Nemotron 3.5 Lightning searched "Benadryl" (left out); the
    # Gemma 4 free models were rate limited upstream at that moment. Free models only.
    llm_backup_models: list[str] = [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "google/gemma-4-31b-it:free",
    ]
    # Speech to text backup: Whisper on Cloudflare Workers AI (free Neurons).
    cloudflare_stt_model: str = "@cf/openai/whisper-large-v3-turbo"
    # bge-m3 on Cloudflare: the same model as `embedding_model`, with identical vectors.
    cloudflare_embedding_model: str = "@cf/baai/bge-m3"
    # Reads boxes and prescriptions (Llama 4 Scout, with image input through the chat endpoint).
    cloudflare_vision_model: str = "@cf/meta/llama-4-scout-17b-16e-instruct"
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

    @property
    def cloudflare_base_url(self) -> str | None:
        """The OpenAI-compatible Workers AI endpoint, when a token and an account are set."""
        if self.cloudflare_api_token is None or not self.cloudflare_account_id:
            return None
        account = self.cloudflare_account_id.strip()
        return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1"

    @field_validator(
        "database_url",
        "redis_url",
        "jwt_secret",
        "openrouter_api_key",
        "groq_api_key",
        "elevenlabs_api_key",
        "tavily_api_key",
        "web_dir",
        "cloudflare_api_token",
        "cloudflare_account_id",
        "smtp_password",
        mode="before",
    )
    @classmethod
    def _empty_means_unset(cls, value: Any) -> Any:
        """`PHARMAVIQUE_REDIS_URL=` (set but empty) is the same as not setting it."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url", mode="after")
    @classmethod
    def _async_driver_address(cls, value: SecretStr | None) -> SecretStr | None:
        """An address from Neon or Vercel works as given (see `foundation.db.url`)."""
        if value is None:
            return None
        return SecretStr(to_asyncpg_url(value.get_secret_value()))


def check_signing_secret(settings: Settings) -> None:
    """In production the API must not start without a strong access-token secret (ADR-020); in
    development and tests a missing or short one is only a warning (accounts answer 503 without it).
    The secret itself is never written anywhere."""
    secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret is not None else ""
    if len(secret) >= MIN_JWT_SECRET_LENGTH:
        return
    problem = (
        "PHARMAVIQUE_JWT_SECRET is not set"
        if not secret
        else f"PHARMAVIQUE_JWT_SECRET is shorter than {MIN_JWT_SECRET_LENGTH} characters"
    )
    if settings.environment == "prod":
        raise RuntimeError(f"{problem}: refusing to start in production")
    logging.getLogger(__name__).warning("%s (allowed outside production)", problem)


@lru_cache
def get_settings() -> Settings:
    return Settings()
