"""Groq speech adapters against a fake endpoint: requests, WAV joining and errors."""

import io
import json
import wave

import httpx
import pytest

from pharmavique.voice.infrastructure.groq_speech import (
    GroqSpeechToText,
    GroqTextToSpeech,
    SpeechError,
    join_wav,
)


def tone(frames: int, rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * frames)
    return buffer.getvalue()


def client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def frames(data: bytes) -> int:
    with wave.open(io.BytesIO(data), "rb") as r:
        return r.getnframes()


def test_wav_parts_are_joined_into_one_file() -> None:
    assert frames(join_wav([tone(100), tone(50)])) == 150


def test_parts_in_different_formats_are_refused() -> None:
    with pytest.raises(SpeechError, match="different formats"):
        join_wav([tone(10, 24000), tone(10, 16000)])


async def test_each_segment_is_one_request_with_the_saudi_voice() -> None:
    bodies: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.groq.com/openai/v1/audio/speech"
        assert request.headers["authorization"] == "Bearer k"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=tone(10))

    tts = GroqTextToSpeech("k", "canopylabs/orpheus-arabic-saudi", "fahad", client(handler))

    audio = await tts.synthesize(["هلا.", "البنادول مسكن."])

    assert frames(audio) == 20
    assert [b["input"] for b in bodies] == ["هلا.", "البنادول مسكن."]
    assert {b["voice"] for b in bodies} == {"fahad"}
    assert {b["response_format"] for b in bodies} == {"wav"}


async def test_a_provider_refusal_names_its_code_but_not_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "model_terms_required"}})

    tts = GroqTextToSpeech("secret", "m", "fahad", client(handler))

    with pytest.raises(SpeechError, match="model_terms_required") as raised:
        await tts.synthesize(["x"])
    assert "secret" not in str(raised.value)


async def test_transcription_uploads_the_audio_with_an_arabic_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
        body = request.content
        assert b'name="language"' in body
        assert b"whisper-large-v3-turbo" in body
        assert b"AUDIO" in body
        return httpx.Response(200, json={"text": " بنادول اكسترا "})

    stt = GroqSpeechToText("k", "whisper-large-v3-turbo", client(handler))

    assert await stt.transcribe(b"AUDIO", "q.m4a", "ar") == " بنادول اكسترا "
