"""ElevenLabs text to speech against a fake endpoint: one request per segment, MP3 joined."""

import json

import httpx
import pytest

from pharmavique.voice.infrastructure.elevenlabs_speech import ElevenLabsTextToSpeech
from pharmavique.voice.infrastructure.groq_speech import SpeechError


def client(handler: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


async def test_each_segment_is_spoken_with_the_configured_voice_and_model() -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["xi-api-key"], json.loads(request.content)))
        return httpx.Response(200, content=b"MP3-" + json.loads(request.content)["text"].encode())

    tts = ElevenLabsTextToSpeech("k", "voice-1", "eleven_v3", client(handler))

    audio = await tts.synthesize(["هلا.", "البنادول مسكن."])

    assert audio == "MP3-هلا.MP3-البنادول مسكن.".encode()
    assert tts.media_type == "audio/mpeg"
    url, key, body = seen[0]
    assert url == (
        "https://api.elevenlabs.io/v1/text-to-speech/voice-1?output_format=mp3_44100_128"
    )
    assert key == "k"
    assert body == {"text": "هلا.", "model_id": "eleven_v3", "language_code": "ar"}


async def test_a_refusal_is_a_speech_error_without_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"code": "unauthorized"}})

    tts = ElevenLabsTextToSpeech("secret", "v", "eleven_v3", client(handler))

    with pytest.raises(SpeechError, match="HTTP 401") as raised:
        await tts.synthesize(["x"])
    assert "secret" not in str(raised.value)
