"""POST /v1/recognition/scan with fakes: candidates per line, unclear dose, 503 without a key."""

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.recognition.domain.scans import ExtractedLine, MatchCandidate, ScanKind

pytestmark = pytest.mark.usefixtures("ai_open_to_guests")


class FakeReader:
    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]:
        return [ExtractedLine("Panadol Extra 500mg", "Panadol Extra", "500 mg", "tab")]


class FakeFinder:
    async def find(self, query: str, limit: int) -> list[MatchCandidate]:
        return [MatchCandidate("1-1", "بانادول اكسترا", "PANADOL EXTRA TAB", 0.8123)]


def client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_a_prescription_photo_returns_lines_to_review() -> None:
    app = create_app(scanner=ScanImage(FakeReader(), FakeFinder()))
    async with client(app) as c:
        response = await c.post(
            "/v1/recognition/scan",
            params={"kind": "prescription"},
            files={"image": ("rx.png", b"\x89PNG....", "image/png")},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "needs_review"
    (line,) = body["lines"]
    assert line["dose"] == "غير واضح"
    assert line["needs_review"] is True
    assert line["confidence"] == "uncertain"  # 0.812 is below the default threshold
    assert line["candidates"][0] == {
        "register_number": "1-1",
        "trade_name_ar": "بانادول اكسترا",
        "trade_name_en": "PANADOL EXTRA TAB",
        "score": 0.812,
    }


async def test_a_document_upload_is_refused() -> None:
    app = create_app(scanner=ScanImage(FakeReader(), FakeFinder()))
    async with client(app) as c:
        response = await c.post(
            "/v1/recognition/scan", files={"image": ("x.pdf", b"%PDF", "application/pdf")}
        )

    assert response.status_code == 422


async def test_without_a_vision_key_scanning_says_so() -> None:
    async with client(create_app()) as c:
        response = await c.post(
            "/v1/recognition/scan", files={"image": ("a.png", b"\x89PNG", "image/png")}
        )

    assert response.status_code == 503
