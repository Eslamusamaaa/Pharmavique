"""Scanning a box or a prescription: read lines, find registry candidates, never guess a dose."""

import pytest

from pharmavique.recognition.application.scan import MAX_IMAGE_BYTES, ScanImage
from pharmavique.recognition.domain.scans import (
    UNCLEAR_DOSE,
    ExtractedLine,
    MatchCandidate,
    ScanKind,
)


class FakeReader:
    def __init__(self, lines: list[ExtractedLine]) -> None:
        self.lines = lines
        self.seen: list[tuple[int, str, ScanKind]] = []

    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]:
        self.seen.append((len(image), media_type, kind))
        return self.lines


class FakeFinder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def find(self, query: str, limit: int) -> list[MatchCandidate]:
        self.queries.append(query)
        if "بنادول" in query or "PANADOL" in query.upper():
            return [MatchCandidate("1-1", "بانادول اكسترا", "PANADOL EXTRA TAB", 0.8)]
        return []


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


async def test_a_prescription_line_gets_candidates_and_an_unclear_dose() -> None:
    reader = FakeReader(
        [ExtractedLine("Panadol Extra 500mg tab", "Panadol Extra", "500 mg", "tab")]
    )
    finder = FakeFinder()

    result = await ScanImage(reader, finder).run(PNG, "image/png", ScanKind.PRESCRIPTION)

    (line,) = result.lines
    assert line.candidates[0].register_number == "1-1"
    assert line.dose == UNCLEAR_DOSE
    assert line.needs_review is True
    assert result.status == "needs_review"
    assert finder.queries == ["Panadol Extra 500 mg"]


async def test_a_box_has_no_dose_field() -> None:
    reader = FakeReader([ExtractedLine("PANADOL EXTRA", "PANADOL EXTRA", None, None)])

    result = await ScanImage(reader, FakeFinder()).run(PNG, "image/png", ScanKind.BOX)

    assert result.lines[0].dose is None
    assert result.lines[0].needs_review is True


async def test_an_unreadable_image_says_so() -> None:
    result = await ScanImage(FakeReader([]), FakeFinder()).run(PNG, "image/png", ScanKind.BOX)

    assert result.status == "nothing_read"
    assert result.lines == ()


async def test_lines_without_a_name_are_dropped_and_their_number_is_capped() -> None:
    lines = [ExtractedLine("x", "", None, None)] + [
        ExtractedLine(f"line {i}", f"name {i}", None, None) for i in range(40)
    ]

    result = await ScanImage(FakeReader(lines), FakeFinder()).run(PNG, "image/png", ScanKind.BOX)

    assert len(result.lines) == 15


@pytest.mark.parametrize(
    ("image", "media_type"),
    [(b"", "image/png"), (PNG, "application/pdf"), (b"0" * (MAX_IMAGE_BYTES + 1), "image/jpeg")],
)
async def test_bad_images_are_refused_before_any_model_call(image: bytes, media_type: str) -> None:
    reader = FakeReader([])

    with pytest.raises(ValueError, match="image"):
        await ScanImage(reader, FakeFinder()).run(image, media_type, ScanKind.BOX)
    assert reader.seen == []
