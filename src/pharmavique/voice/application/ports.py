"""Speech ports (ADR-005). Audio is health-adjacent data: adapters keep it in memory only and
never write it to disk or logs."""

from collections.abc import Sequence
from typing import Protocol


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, filename: str, language: str) -> str: ...


class TextToSpeech(Protocol):
    """A voice provider. Each declares how much text one request takes and what it returns."""

    @property
    def max_segment(self) -> int: ...

    @property
    def media_type(self) -> str: ...

    async def synthesize(self, segments: Sequence[str]) -> bytes:
        """One audio file speaking every segment in order."""
        ...


class DrugNameExtractor(Protocol):
    """Picks the medicine name out of a spoken request (a language model)."""

    async def extract(self, text: str) -> str | None:
        """The name as spoken, or None when no medicine is named."""
        ...
