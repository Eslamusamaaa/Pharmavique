"""Speech to text over Cloudflare Workers AI (Whisper large v3 turbo), the free backup of Groq.

Cloudflare's OpenAI-compatible routes have no audio endpoint ("No route for that URI", checked
2026-11-24), so this uses the model's own route: POST `/ai/run/<model>` with the audio in base64
and a language hint; the text comes back in `result.text`. Audio stays in memory; nothing is
written to disk or logs. The token goes only in the header.
"""

import base64

import httpx

from pharmavique.voice.infrastructure.groq_speech import SpeechError

API_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"


class CloudflareSpeechToText:
    def __init__(
        self, account_id: str, api_token: str, model: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._url = API_URL.format(account=account_id.strip(), model=model)
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self._client = client or httpx.AsyncClient(timeout=60.0)

    async def transcribe(self, audio: bytes, filename: str, language: str) -> str:
        payload = {"audio": base64.b64encode(audio).decode("ascii"), "language": language}
        try:
            response = await self._client.post(self._url, headers=self._headers, json=payload)
        except httpx.HTTPError as error:
            raise SpeechError(f"speech provider unreachable ({type(error).__name__})") from error
        if response.status_code != 200:
            raise SpeechError(f"speech provider answered HTTP {response.status_code}")
        try:
            result = response.json().get("result") or {}
        except ValueError as error:
            raise SpeechError("speech provider answered something that is not JSON") from error
        return str(result.get("text", ""))
