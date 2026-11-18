"""Text to speech over ElevenLabs (owner's choice, 2026-11-19), MP3 output.

The Saudi dialect comes from the text (the assistant writes spoken answers in Saudi dialect) and
from the voice: the voice id is configuration, so a Saudi voice from the ElevenLabs voice library
is used by setting PHARMAVIQUE_ELEVENLABS_VOICE_ID. Audio stays in memory; the key goes only in
the `xi-api-key` header.
"""

from collections.abc import Sequence

import httpx

from pharmavique.voice.infrastructure.groq_speech import SpeechError

BASE_URL = "https://api.elevenlabs.io/v1"
OUTPUT_FORMAT = "mp3_44100_128"


class ElevenLabsTextToSpeech:
    max_segment = 1000  # whole answers fit in one request; long texts are cut at sentences
    media_type = "audio/mpeg"

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
        client: httpx.AsyncClient | None = None,
        language_code: str = "ar",
    ) -> None:
        self._headers = {"xi-api-key": api_key}
        self._voice_id = voice_id
        self._model_id = model_id
        self._language = language_code
        self._client = client or httpx.AsyncClient(timeout=90.0)

    async def synthesize(self, segments: Sequence[str]) -> bytes:
        parts: list[bytes] = []
        url = f"{BASE_URL}/text-to-speech/{self._voice_id}?output_format={OUTPUT_FORMAT}"
        for segment in segments:
            response = await self._client.post(
                url,
                headers=self._headers,
                json={"text": segment, "model_id": self._model_id, "language_code": self._language},
            )
            if response.status_code != 200:
                raise SpeechError(f"speech provider answered HTTP {response.status_code}")
            parts.append(response.content)
        if not parts:
            raise SpeechError("nothing to synthesize")
        return b"".join(parts)  # MP3 frames play back to back
