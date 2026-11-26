"""`VisionReader` over an OpenAI-compatible chat endpoint with image input (OpenRouter by default).

The model only transcribes: medicine names, strengths and dosage forms as printed or written. It
is told not to read doses or instructions, and the domain discards them anyway. The image is sent
as a data URL in memory; it is never written to disk or logs, and the key goes only in the header.
"""

import asyncio
import base64
import io
import json
import re
import time
from collections.abc import Sequence
from typing import Any

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from pharmavique.foundation.http.client import async_client
from pharmavique.recognition.application.ports import VisionReader
from pharmavique.recognition.domain.scans import ExtractedLine, ScanKind

MAX_SIDE = 1600  # pixels: enough to read a printed name, small enough for a free model to answer
_KEEP_AS_IS_BYTES = 1_500_000


def shrink(image: bytes, media_type: str) -> tuple[bytes, str]:
    """A phone photo is many megapixels and several MB: free vision models often time out or refuse
    it. Shrink what is large to a JPEG whose longer side is at most `MAX_SIDE`, upright as the phone
    meant it. A small picture, or bytes that are not an image, are returned untouched."""
    try:
        with Image.open(io.BytesIO(image)) as opened:
            if max(opened.size) <= MAX_SIDE and len(image) <= _KEEP_AS_IS_BYTES:
                return image, media_type
            upright = ImageOps.exif_transpose(opened).convert("RGB")
            upright.thumbnail((MAX_SIDE, MAX_SIDE))
            buffer = io.BytesIO()
            upright.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, OSError, ValueError):
        return image, media_type


_PROMPTS = {
    ScanKind.BOX: (
        "This is a photo of a medicine box or pack. Transcribe the medicine it is: the trade name "
        "exactly as printed (Arabic or English), the strength (for example 500 mg) and the dosage "
        "form (tablet, syrup, ...)."
    ),
    ScanKind.SHELF: (
        "This is a photo of a pharmacy shelf with several medicine boxes. List every box whose "
        "name you can read, one line per distinct box: the trade name exactly as printed "
        "(Arabic or English), the strength and the dosage form when printed. Do NOT count "
        "units, do not identify a box by its colour or shape, and do not read prices."
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
    """The lines in the model's JSON answer. An answer that is not the asked JSON (prose, a refusal,
    broken JSON, no `lines` list) raises `VisionError`, so the next model is tried; a valid answer
    with no legible medicine gives no lines. A line without a name is left out, never guessed."""
    match = _JSON.search(content or "")
    if match is None:
        raise VisionError("the model's answer is not the asked JSON (no JSON object)")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise VisionError("the model's answer is not the asked JSON (broken JSON)") from error
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        raise VisionError("the model's answer is not the asked JSON (no lines list)")
    lines = []
    for item in data["lines"]:
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
        self._client = client or async_client(timeout=timeout)

    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]:
        image, media_type = shrink(image, media_type)
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
        try:
            response = await self._client.post(self._url, json=payload, headers=self._headers)
        except httpx.TransportError as error:
            # a dropped or refused connection, also in the middle of the answer: a failure of this
            # provider like any other, so the next model is tried and the API answers 502, not 500
            raise VisionError(
                f"vision provider connection failed ({type(error).__name__})"
            ) from error
        if response.status_code != 200:
            raise VisionError(
                f"{self._model}: vision provider answered HTTP {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise VisionError(f"{self._model}: answered something that is not JSON") from error
        choices = (body.get("choices") if isinstance(body, dict) else None) or []
        content = (choices[0].get("message") or {}).get("content") if choices else ""
        return parse_lines(content if isinstance(content, str) else "")


class FallbackVisionReader:
    """Tries each reader in order until one gives a valid answer: free models are often busy (HTTP
    429), slow, or answer with prose. Each reader gets at most `per_reader_seconds`, and the whole
    chain stops at `total_seconds`, which must stay below the job timeout and Vercel's limit
    (audit 2026-11, A2). A valid empty answer ("no medicine here") is a result, not a failure."""

    def __init__(
        self,
        readers: Sequence[VisionReader],
        *,
        per_reader_seconds: float = 20.0,
        total_seconds: float = 60.0,
    ) -> None:
        if not readers:
            raise ValueError("at least one vision reader is needed")
        if per_reader_seconds <= 0 or total_seconds <= 0:
            raise ValueError("the vision time limits must be positive")
        self._readers = list(readers)
        self._per_reader = per_reader_seconds
        self._total = total_seconds

    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]:
        failures: list[str] = []
        deadline = time.monotonic() + self._total
        for reader in self._readers:
            left = deadline - time.monotonic()
            if left <= 0:
                failures.append("the scan timed out before every model was tried")
                break
            try:
                async with asyncio.timeout(min(self._per_reader, left)):
                    return await reader.read(image, media_type, kind)
            except VisionError as failure:
                failures.append(str(failure))
            except (TimeoutError, httpx.TimeoutException):
                failures.append("a model timed out")
        raise VisionError("; ".join(failures))
