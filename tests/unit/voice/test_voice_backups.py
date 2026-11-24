"""Listening and speaking go on to a free backup when a provider fails (owner, 2026-11-24)."""

import base64
import json
from collections.abc import Sequence

import httpx
import pytest

from pharmavique.voice.application.speak import Speak, Transcribe
from pharmavique.voice.infrastructure.cloudflare_speech import CloudflareSpeechToText
from pharmavique.voice.infrastructure.groq_speech import GroqSpeechToText, SpeechError


class Voice:
    def __init__(self, max_segment: int, media_type: str, fails: bool = False) -> None:
        self.max_segment = max_segment
        self.media_type = media_type
        self.fails = fails
        self.calls: list[list[str]] = []

    async def synthesize(self, segments: Sequence[str]) -> bytes:
        self.calls.append(list(segments))
        if self.fails:
            raise SpeechError("speech provider answered HTTP 401")
        return self.media_type.encode()


class Listener:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, audio: bytes, filename: str, language: str) -> str:
        self.calls += 1
        if self.text is None:
            raise httpx.ConnectError("refused")
        return self.text


async def test_speech_goes_to_the_backup_voice_cut_to_its_own_length() -> None:
    first, backup = Voice(1000, "audio/mpeg", fails=True), Voice(20, "audio/wav")
    text = "البنادول مسكن للألم. وهو خافض للحرارة."

    audio = await Speak(first, backup).run(text)

    assert audio.media_type == "audio/wav"
    assert len(first.calls[0]) == 1
    assert len(backup.calls[0]) > 1
    assert all(len(s) <= 20 for s in backup.calls[0])


async def test_when_every_voice_fails_the_last_error_is_raised() -> None:
    with pytest.raises(SpeechError):
        await Speak(Voice(200, "a", fails=True), Voice(200, "b", fails=True)).run("هلا.")


async def test_listening_goes_to_the_backup() -> None:
    first, backup = Listener(None), Listener(" هلا ")

    assert await Transcribe(first, backup).run(b"abc", "a.m4a") == "هلا"
    assert (first.calls, backup.calls) == (1, 1)


async def test_a_refused_connection_to_groq_is_a_speech_error_not_a_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    stt = GroqSpeechToText(
        "k", "whisper", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(SpeechError, match="unreachable"):
        await stt.transcribe(b"abc", "a.m4a", "ar")


async def test_cloudflare_whisper_sends_the_audio_in_base64_and_reads_result_text() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": {"text": "بنادول"}, "success": True})

    stt = CloudflareSpeechToText(
        " acc ",
        "tok",
        "@cf/openai/whisper-large-v3-turbo",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    assert await stt.transcribe(b"abc", "a.m4a", "ar") == "بنادول"
    assert seen["url"] == (
        "https://api.cloudflare.com/client/v4/accounts/acc/ai/run/@cf/openai/whisper-large-v3-turbo"
    )
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"audio": base64.b64encode(b"abc").decode(), "language": "ar"}


async def test_cloudflare_whisper_errors_are_speech_errors() -> None:
    stt = CloudflareSpeechToText(
        "acc",
        "tok",
        "m",
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429))),
    )

    with pytest.raises(SpeechError, match="429"):
        await stt.transcribe(b"abc", "a.m4a", "ar")
