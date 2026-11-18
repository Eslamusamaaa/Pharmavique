"""Scan a box or a prescription: read the lines, then find registry candidates for each.

The first version answers within the request and keeps nothing (no job table, no stored image):
the image is read in memory and dropped. Jobs with a review state come with accounts.
"""

from pharmavique.recognition.application.ports import CandidateFinder, VisionReader
from pharmavique.recognition.domain.scans import (
    MAX_LINES,
    UNCLEAR_DOSE,
    LineResult,
    ScanKind,
    ScanResult,
)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
CANDIDATES_PER_LINE = 3


class ScanImage:
    def __init__(self, reader: VisionReader, finder: CandidateFinder) -> None:
        self._reader = reader
        self._finder = finder

    async def run(self, image: bytes, media_type: str, kind: ScanKind) -> ScanResult:
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise ValueError("the image must be between 1 byte and 8 MB")
        if media_type not in IMAGE_TYPES:
            raise ValueError("the image must be a JPEG, PNG or WebP picture")
        lines = [line for line in await self._reader.read(image, media_type, kind) if line.name]
        results = []
        for line in lines[:MAX_LINES]:
            candidates = await self._finder.find(line.query(), CANDIDATES_PER_LINE)
            dose = UNCLEAR_DOSE if kind is ScanKind.PRESCRIPTION else None
            results.append(LineResult(line, tuple(candidates), dose))
        return ScanResult(kind, tuple(results))
