"""Voice endpoints: transcribe an uploaded question, speak a text as WAV; 503 without a key."""

from collections.abc import Sequence

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.voice.application.speak import Speak, Transcribe

pytestmark = pytest.mark.usefixtures("ai_open_to_guests")


class FakeSTT:
    async def transcribe(self, audio: bytes, filename: str, language: str) -> str:
        return f"بنادول ({language}, {len(audio)} bytes)"


class FakeTTS:
    max_segment = 200
    media_type = "audio/mpeg"

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
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"RIFF....WAVE"
    assert tts.segments == ["البنادول مسكن."]


async def test_without_a_speech_key_the_endpoints_say_so() -> None:
    async with client(create_app()) as c:
        spoken = await c.post("/v1/voice/speak", json={"text": "هلا"})
        heard = await c.post("/v1/voice/transcribe", files={"audio": ("q.m4a", b"1")})

    assert spoken.status_code == 503
    assert heard.status_code == 503


async def test_a_spoken_answer_can_be_fetched_once_by_a_short_lived_link() -> None:
    tts = FakeTTS()
    app = create_app(speak=Speak(tts))
    async with client(app) as c:
        linked = await c.post("/v1/voice/speak", json={"text": "البنادول مسكن.", "as_link": True})
        audio = await c.get(linked.json()["url"])
        again = await c.get(linked.json()["url"])

    assert linked.status_code == 200
    assert linked.json()["media_type"] == "audio/mpeg"
    assert audio.status_code == 200
    assert audio.content == b"RIFF....WAVE"
    assert audio.headers["content-type"] == "audio/mpeg"
    assert again.status_code == 404  # served once, then gone


async def test_an_unknown_audio_link_is_a_404() -> None:
    async with client(create_app(speak=Speak(FakeTTS()))) as c:
        assert (await c.get("/v1/voice/audio/abc")).status_code == 404


class NamingModel:
    async def extract(self, text: str) -> str | None:
        return "بنادول"


async def test_the_drug_name_endpoint_returns_what_to_search_for() -> None:
    async with client(create_app(name_extractor=NamingModel())) as c:
        response = await c.post("/v1/voice/drug-name", json={"text": "أنا عايز بنادول"})

    assert response.status_code == 200
    assert response.json() == {"query": "بنادول", "name": "بنادول", "understood": True}


async def test_the_drug_name_endpoint_still_cleans_the_text_without_a_model() -> None:
    async with client(create_app()) as c:
        response = await c.post("/v1/voice/drug-name", json={"text": "انا عايز بروفين"})

    assert response.json() == {"query": "بروفين", "name": None, "understood": False}
