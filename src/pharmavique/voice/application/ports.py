"""Speech ports (ADR-005). Audio is health-adjacent data: adapters keep it in memory only and
never write it to disk or logs."""

from collections.abc import Sequence
from typing import Protocol


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, filename: str, language: str) -> str: ...


class TextToSpeech(Protocol):
    async def synthesize(self, segments: Sequence[str]) -> bytes:
        """One audio file (WAV) speaking every segment in order."""
        ...
