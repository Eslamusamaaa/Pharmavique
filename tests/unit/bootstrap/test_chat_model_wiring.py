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


def test_the_embedder_uses_cloudflare_but_keeps_the_stored_model_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pharmavique.bootstrap.ai import build_embedder

    cloud = settings(
        monkeypatch,
        {
            "OPENROUTER_API_KEY": "o",
            "CLOUDFLARE_API_TOKEN": "t",
            "CLOUDFLARE_ACCOUNT_ID": "abc123",
        },
    )
    embedder = build_embedder(cloud)

    assert embedder is not None
    assert embedder.model == "baai/bge-m3"
    assert embedder.url == "https://api.cloudflare.com/client/v4/accounts/abc123/ai/v1/embeddings"


def test_the_embedder_falls_back_to_openrouter_without_cloudflare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pharmavique.bootstrap.ai import build_embedder

    embedder = build_embedder(settings(monkeypatch, {"OPENROUTER_API_KEY": "o"}))

    assert embedder is not None
    assert embedder.url == "https://openrouter.ai/api/v1/embeddings"


def test_the_scanner_can_run_on_cloudflare_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    from typing import Any, cast

    from pharmavique.bootstrap.ai import build_scanner

    nothing = cast(Any, None)
    cloud = settings(monkeypatch, {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "abc123"})

    assert build_scanner(cloud, search=nothing, catalog=nothing) is not None
    assert build_scanner(settings(monkeypatch), search=nothing, catalog=nothing) is None


def test_every_free_model_with_a_key_joins_the_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    model = build_chat_model(
        settings(
            monkeypatch,
            {
                "GROQ_API_KEY": "g",
                "OPENROUTER_API_KEY": "o",
                "CLOUDFLARE_API_TOKEN": "t",
                "CLOUDFLARE_ACCOUNT_ID": "abc123",
            },
        )
    )

    assert isinstance(model, FallbackChatModel)
    assert model.model_names == [
        "openai/gpt-oss-120b",
        "@cf/google/gemma-4-26b-a4b-it",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "google/gemma-4-31b-it:free",
    ]
    assert all(name.endswith(":free") for name in model.model_names[2:])


def test_the_embedder_has_openrouter_as_its_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    from pharmavique.bootstrap.ai import build_embedder

    embedder = build_embedder(
        settings(
            monkeypatch,
            {"OPENROUTER_API_KEY": "o", "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a"},
        )
    )

    assert embedder is not None
    assert [e.url for e in embedder._embedders] == [
        "https://api.cloudflare.com/client/v4/accounts/a/ai/v1/embeddings",
        "https://openrouter.ai/api/v1/embeddings",
    ]


def test_voice_has_a_backup_for_listening_and_speaking(monkeypatch: pytest.MonkeyPatch) -> None:
    from pharmavique.bootstrap.ai import build_stt, build_tts
    from pharmavique.voice.infrastructure.cloudflare_speech import CloudflareSpeechToText
    from pharmavique.voice.infrastructure.elevenlabs_speech import ElevenLabsTextToSpeech
    from pharmavique.voice.infrastructure.groq_speech import GroqSpeechToText, GroqTextToSpeech

    monkeypatch.delenv("PHARMAVIQUE_TTS_PROVIDER", raising=False)
    env = settings(
        monkeypatch,
        {
            "GROQ_API_KEY": "g",
            "ELEVENLABS_API_KEY": "e",
            "CLOUDFLARE_API_TOKEN": "t",
            "CLOUDFLARE_ACCOUNT_ID": "a",
        },
    )

    assert [type(s) for s in build_stt(env)] == [GroqSpeechToText, CloudflareSpeechToText]
    assert [type(v) for v in build_tts(env)] == [ElevenLabsTextToSpeech, GroqTextToSpeech]
