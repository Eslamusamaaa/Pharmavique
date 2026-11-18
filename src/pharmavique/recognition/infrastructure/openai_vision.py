"""`VisionReader` over an OpenAI-compatible chat endpoint with image input (OpenRouter by default).

The model only transcribes: medicine names, strengths and dosage forms as printed or written. It
is told not to read doses or instructions, and the domain discards them anyway. The image is sent
as a data URL in memory; it is never written to disk or logs, and the key goes only in the header.
"""

import base64
import json
import re
from collections.abc import Sequence
from typing import Any

import httpx

from pharmavique.recognition.application.ports import VisionReader
from pharmavique.recognition.domain.scans import ExtractedLine, ScanKind

_PROMPTS = {
    ScanKind.BOX: (
        "This is a photo of a medicine box or pack. Transcribe the medicine it is: the trade name "
        "exactly as printed (Arabic or English), the strength (for example 500 mg) and the dosage "
        "form (tablet, syrup, ...)."
    ),
    ScanKind.PRESCRIPTION: (
        "This is a photo of a medical prescription (printed or handwritten, Arabic or English). "
        "List every medicine written on it: the name exactly as written, its strength and dosage "
        "form when written. Do NOT read doses, frequencies, durations or instructions."
    ),
}
_FORMAT = (
    ' Answer with JSON only, no prose: {"lines": [{"raw_text": "...", "name": "...", '
    '"strength": "... or null", "form": "... or null"}]}. Never guess: if a name is not legible, '
    'leave it out. If there is no medicine, answer {"lines": []}.'
)
_JSON = re.compile(r"\{.*\}", re.DOTALL)


class VisionError(RuntimeError):
    pass


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"null", "none", "-"} else None


def parse_lines(content: str) -> list[ExtractedLine]:
    """The lines in the model's JSON answer; anything unreadable gives no lines, never a guess."""
    match = _JSON.search(content or "")
    if match is None:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    lines = []
    for item in data.get("lines", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if name is None:
            continue
        lines.append(
            ExtractedLine(
                raw_text=_text(item.get("raw_text")) or name,
                name=name,
                strength=_text(item.get("strength")),
                form=_text(item.get("form")),
            )
        )
    return lines


class OpenAICompatibleVisionReader:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 90.0,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]:
        data_url = f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPTS[kind] + _FORMAT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
        response = await self._client.post(self._url, json=payload, headers=self._headers)
        if response.status_code != 200:
            raise VisionError(f"vision provider answered HTTP {response.status_code}")
        choices = response.json().get("choices") or []
        content = (choices[0].get("message") or {}).get("content") if choices else ""
        return parse_lines(content if isinstance(content, str) else "")


class FallbackVisionReader:
    """Tries each reader in order until one answers: free models are often busy (HTTP 429)."""

    def __init__(self, readers: Sequence[VisionReader]) -> None:
        if not readers:
            raise ValueError("at least one vision reader is needed")
        self._readers = list(readers)

    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]:
        error: VisionError | None = None
        for reader in self._readers:
            try:
                return await reader.read(image, media_type, kind)
            except (VisionError, httpx.TimeoutException) as failure:
                error = failure if isinstance(failure, VisionError) else VisionError("timed out")
        assert error is not None  # noqa: S101 (the loop ran at least once)
        raise error
