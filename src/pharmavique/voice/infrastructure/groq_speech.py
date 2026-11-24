"""Speech adapters over Groq's OpenAI-compatible audio endpoints (ADR-005).

- Speech to text: Whisper (`/audio/transcriptions`, multipart upload, language hint).
- Text to speech: Orpheus Arabic Saudi (`/audio/speech`), WAV only, 200 characters per request;
  segments are spoken one by one and joined into one WAV file.
Audio stays in memory; nothing is written to disk or logs. The key goes only in the header.
"""

import io
import wave
from collections.abc import Sequence

import httpx

BASE_URL = "https://api.groq.com/openai/v1"


class SpeechError(RuntimeError):
    pass


def _error(response: httpx.Response) -> SpeechError:
    code = ""
    try:
        code = response.json().get("error", {}).get("code") or ""
    except ValueError:
        code = ""
    detail = f" ({code})" if code else ""
    return SpeechError(f"speech provider answered HTTP {response.status_code}{detail}")


def join_wav(parts: Sequence[bytes]) -> bytes:
    """Concatenate WAV files that share one format into one WAV file."""
    if len(parts) == 1:
        return parts[0]
    out = io.BytesIO()
    params = None
    with wave.open(out, "wb") as writer:
        for part in parts:
            with wave.open(io.BytesIO(part), "rb") as reader:
                current = reader.getparams()
                if params is None:
                    params = current
                    writer.setparams(current)
                elif current[:3] != params[:3]:
                    raise SpeechError("audio segments came back in different formats")
                writer.writeframes(reader.readframes(reader.getnframes()))
    return out.getvalue()


class GroqSpeechToText:
    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=60.0)

    async def transcribe(self, audio: bytes, filename: str, language: str) -> str:
        try:
            response = await self._client.post(
                f"{BASE_URL}/audio/transcriptions",
                headers=self._headers,
                data={"model": self._model, "language": language, "response_format": "json"},
                files={"file": (filename, audio)},
            )
        except httpx.HTTPError as error:
            raise SpeechError(f"speech provider unreachable ({type(error).__name__})") from error
        if response.status_code != 200:
            raise _error(response)
        return str(response.json().get("text", ""))


class GroqTextToSpeech:
    max_segment = 200  # Orpheus takes at most 200 characters per request
    media_type = "audio/wav"

    def __init__(
        self, api_key: str, model: str, voice: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._voice = voice
        self._client = client or httpx.AsyncClient(timeout=60.0)

    async def synthesize(self, segments: Sequence[str]) -> bytes:
        parts = []
        for segment in segments:
            try:
                response = await self._client.post(
                    f"{BASE_URL}/audio/speech",
                    headers=self._headers,
                    json={
                        "model": self._model,
                        "voice": self._voice,
                        "input": segment,
                        "response_format": "wav",
                    },
                )
            except httpx.HTTPError as error:
                raise SpeechError(
                    f"speech provider unreachable ({type(error).__name__})"
                ) from error
            if response.status_code != 200:
                raise _error(response)
            parts.append(response.content)
        if not parts:
            raise SpeechError("nothing to synthesize")
        return join_wav(parts)
