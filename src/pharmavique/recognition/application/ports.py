"""Ports of recognition (ADR-005, AI_ARCHITECTURE.md section 4)."""

from typing import Protocol

from pharmavique.recognition.domain.scans import ExtractedLine, MatchCandidate, ScanKind


class VisionReader(Protocol):
    """Reads the medicines on an image. The image stays in memory and is never stored."""

    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]: ...


class CandidateFinder(Protocol):
    """Registry candidates for a read name (the same search as typed text)."""

    async def find(self, query: str, limit: int) -> list[MatchCandidate]: ...
