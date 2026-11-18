"""Voice endpoints: transcribe an uploaded question, speak a text as WAV; 503 without a key."""

from collections.abc import Sequence

import httpx

from pharmavique.bootstrap.api import create_app
from pharmavique.voice.application.speak import Speak, Transcribe


class FakeSTT:
    async def transcribe(self, audio: bytes, filename: str, language: str) -> str:
        return f"بنادول ({language}, {len(audio)} bytes)"


class FakeTTS:
    def __init__(self) -> None:
        self.segments: list[str] = []

    async def synthesize(self, segments: Sequence[str]) -> bytes:
        self.segments.extend(segments)
        return b"RIFF....WAVE"


def client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_an_uploaded_question_is_transcribed_in_arabic() -> None:
    app = create_app(transcribe=Transcribe(FakeSTT()))
    async with client(app) as c:
        response = await c.post(
            "/v1/voice/transcribe", files={"audio": ("q.m4a", b"12345", "audio/m4a")}
        )

    assert response.status_code == 200
    assert response.json() == {"text": "بنادول (ar, 5 bytes)"}


async def test_a_text_is_spoken_as_wav_without_its_citation_marks() -> None:
    tts = FakeTTS()
    app = create_app(speak=Speak(tts))
    async with client(app) as c:
        response = await c.post("/v1/voice/speak", json={"text": "البنادول مسكن [1]."})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFF....WAVE"
    assert tts.segments == ["البنادول مسكن."]


async def test_without_a_speech_key_the_endpoints_say_so() -> None:
    async with client(create_app()) as c:
        spoken = await c.post("/v1/voice/speak", json={"text": "هلا"})
        heard = await c.post("/v1/voice/transcribe", files={"audio": ("q.m4a", b"1")})

    assert spoken.status_code == 503
    assert heard.status_code == 503
