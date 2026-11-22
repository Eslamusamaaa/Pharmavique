"""The assistant's chat model: Groq alone, or Groq with Cloudflare as its backup."""

import pytest

from pharmavique.assistant.infrastructure.fallback_model import FallbackChatModel
from pharmavique.bootstrap.ai import build_chat_model
from pharmavique.bootstrap.settings import Settings


def settings(monkeypatch: pytest.MonkeyPatch, env: dict[str, str] | None = None) -> Settings:
    for name in (
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    ):
        monkeypatch.delenv(f"PHARMAVIQUE_{name}", raising=False)
    for name, value in (env or {}).items():
        monkeypatch.setenv(f"PHARMAVIQUE_{name}", value)
    return Settings(_env_file=None)


def test_without_a_key_there_is_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    assert build_chat_model(settings(monkeypatch)) is None


def test_groq_alone_is_a_plain_model(monkeypatch: pytest.MonkeyPatch) -> None:
    model = build_chat_model(settings(monkeypatch, {"GROQ_API_KEY": "g"}))

    assert model is not None
    assert not isinstance(model, FallbackChatModel)


def test_cloudflare_becomes_the_backup_of_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    model = build_chat_model(
        settings(
            monkeypatch,
            {
                "GROQ_API_KEY": "g",
                "CLOUDFLARE_API_TOKEN": "t",
                "CLOUDFLARE_ACCOUNT_ID": "abc123",
            },
        )
    )

    assert isinstance(model, FallbackChatModel)
    assert model.model_name == "openai/gpt-oss-120b"


def test_cloudflare_alone_still_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    model = build_chat_model(
        settings(monkeypatch, {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "abc123"})
    )

    assert model is not None
    assert not isinstance(model, FallbackChatModel)
