"""The pharmacist's shelf scan (behind a flag) and the shelf list they confirm into."""

from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.foundation.clock import SystemClock
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.recognition.domain.scans import ExtractedLine, MatchCandidate, ScanKind
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.principal import Principal, Role
from pharmavique.watchlist.application.shelf import ShelfService
from pharmavique.watchlist.domain.model import ShelfItem


class Reader:
    def __init__(self) -> None:
        self.kinds: list[ScanKind] = []

    async def read(self, image: bytes, media_type: str, kind: ScanKind) -> list[ExtractedLine]:
        self.kinds.append(kind)
        return [
            ExtractedLine("Panadol Extra 500", "Panadol Extra", "500 mg", None),
            ExtractedLine("Brufen 400", "Brufen", "400 mg", None),
        ]


class Finder:
    async def find(self, query: str, limit: int) -> list[MatchCandidate]:
        return [MatchCandidate("1", "بانادول", "PANADOL EXTRA", 0.81)]


class ShelfStore:
    def __init__(self) -> None:
        self.items: dict[UUID, dict[str, datetime]] = {}

    async def add_shelf_items(
        self, user_id: UUID, register_numbers: Iterable[str], at: datetime
    ) -> int:
        mine = self.items.setdefault(user_id, {})
        added = 0
        for number in register_numbers:
            if number not in mine:
                mine[number] = at
                added += 1
        return added

    async def remove_shelf_item(self, user_id: UUID, register_number: str) -> bool:
        return self.items.get(user_id, {}).pop(register_number, None) is not None

    async def shelf(self, user_id: UUID) -> list[ShelfItem]:
        return [ShelfItem(r, t) for r, t in self.items.get(user_id, {}).items()]


def card(number: str, name: str) -> ProductCard:
    return ProductCard(
        market=Market.SA, register_number=number, trade_name_en=name, trade_name_ar=None,
        ingredient_names=("X",), dosage_form_en="Tablet", dosage_form_ar=None,
        marketing_company="ACME", manufacturers=(), atc_codes=(), listing_status="listed",
        authorization_status=None, marketing_status=None,
    )  # fmt: skip


class Catalog:
    cards: ClassVar[dict[str, ProductCard]] = {
        "1": card("1", "PANADOL EXTRA"),
        "2": card("2", "BRUFEN 400"),
    }

    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(self.cards[n] for n in register_numbers if n in self.cards)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        raise NotImplementedError


TOKENS = JwtAccessTokens("k" * 40)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def headers(role: Role, user: UUID | None = None) -> dict[str, str]:
    token, _ = TOKENS.issue(Principal(user or uuid4(), None, frozenset({role})), datetime.now(UTC))
    return {"Authorization": f"Bearer {token}"}


def make(enabled: bool) -> tuple[httpx.AsyncClient, Reader]:
    reader = Reader()
    app = create_app(
        scanner=ScanImage(reader, Finder()),
        catalog=Catalog(),
        shelf=ShelfService(ShelfStore(), SystemClock()),
        shelf_scan_enabled=enabled,
        token_verifier=TOKENS,
        rate_limit_per_minute=0,
        heavy_rate_limit_per_minute=0,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, reader


@pytest.fixture
async def on() -> AsyncIterator[tuple[httpx.AsyncClient, Reader]]:
    client, reader = make(True)
    async with client:
        yield client, reader


async def scan_shelf(
    client: httpx.AsyncClient, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await client.post(
        "/v1/recognition/scan",
        params={"kind": "shelf"},
        files={"image": ("shelf.png", PNG, "image/png")},
        headers=headers,
    )


async def test_the_features_endpoint_says_whether_the_shelf_scan_is_on() -> None:
    for enabled in (False, True):
        client, _ = make(enabled)
        async with client:
            body = (await client.get("/v1/features")).json()
        assert body["shelf_scan"] is enabled


async def test_a_switched_off_shelf_scan_refuses_everyone() -> None:
    client, reader = make(False)
    async with client:
        response = await scan_shelf(client, headers=headers(Role.PHARMACIST))
    assert response.status_code == 404
    assert reader.kinds == []


async def test_the_shelf_scan_needs_a_signed_in_pharmacist(
    on: tuple[httpx.AsyncClient, Reader],
) -> None:
    client, reader = on
    assert (await scan_shelf(client)).status_code == 401
    assert (await scan_shelf(client, headers=headers(Role.PATIENT))).status_code == 403
    assert (await scan_shelf(client, headers=headers(Role.COMPANY))).status_code == 403
    assert reader.kinds == []


async def test_a_pharmacist_gets_the_boxes_to_review(on: tuple[httpx.AsyncClient, Reader]) -> None:
    client, reader = on
    response = await scan_shelf(client, headers=headers(Role.PHARMACIST))
    body = response.json()
    assert response.status_code == 200
    assert body["kind"] == "shelf"
    assert len(body["lines"]) == 2
    assert all(line["needs_review"] for line in body["lines"])
    assert all(line["dose"] is None for line in body["lines"])
    assert body["lines"][0]["candidates"][0]["score"] == 0.81  # the confidence is always shown
    assert reader.kinds == [ScanKind.SHELF]


async def test_the_box_scan_stays_open_to_everyone_even_with_the_shelf_scan_off() -> None:
    client, _ = make(False)
    async with client:
        response = await client.post(
            "/v1/recognition/scan",
            params={"kind": "box"},
            files={"image": ("a.png", PNG, "image/png")},
        )
    assert response.status_code == 200


async def test_the_shelf_list_is_for_pharmacists_only(
    on: tuple[httpx.AsyncClient, Reader],
) -> None:
    client, _ = on
    assert (await client.get("/v1/me/shelf")).status_code == 401
    assert (await client.get("/v1/me/shelf", headers=headers(Role.PATIENT))).status_code == 403
    assert (
        await client.post(
            "/v1/me/shelf", json={"register_numbers": ["1"]}, headers=headers(Role.PATIENT)
        )
    ).status_code == 403


async def test_confirmed_boxes_join_the_list_and_unknown_ones_are_not_added(
    on: tuple[httpx.AsyncClient, Reader],
) -> None:
    client, _ = on
    me = headers(Role.PHARMACIST)

    first = (
        await client.post("/v1/me/shelf", json={"register_numbers": ["1", "2", "999"]}, headers=me)
    ).json()
    again = (await client.post("/v1/me/shelf", json={"register_numbers": ["1"]}, headers=me)).json()

    assert first == {"added": 2, "already_on_the_shelf": 0, "unknown": ["999"]}
    assert again == {"added": 0, "already_on_the_shelf": 1, "unknown": []}
    listing = (await client.get("/v1/me/shelf", headers=me)).json()
    assert listing["count"] == 2
    assert {i["product"]["trade_name_en"] for i in listing["items"]} == {
        "PANADOL EXTRA",
        "BRUFEN 400",
    }
    assert "stock" in listing["note"]


async def test_a_medicine_can_come_off_the_list(on: tuple[httpx.AsyncClient, Reader]) -> None:
    client, _ = on
    me = headers(Role.PHARMACIST)
    await client.post("/v1/me/shelf", json={"register_numbers": ["1"]}, headers=me)
    assert (await client.delete("/v1/me/shelf/1", headers=me)).status_code == 204
    assert (await client.get("/v1/me/shelf", headers=me)).json()["count"] == 0


async def test_one_pharmacists_shelf_is_not_anothers(on: tuple[httpx.AsyncClient, Reader]) -> None:
    client, _ = on
    a = headers(Role.PHARMACIST)
    b = headers(Role.PHARMACIST)
    await client.post("/v1/me/shelf", json={"register_numbers": ["1"]}, headers=a)
    assert (await client.get("/v1/me/shelf", headers=b)).json()["count"] == 0


async def test_confirming_nothing_or_too_many_at_once_is_refused(
    on: tuple[httpx.AsyncClient, Reader],
) -> None:
    client, _ = on
    me = headers(Role.PHARMACIST)
    assert (
        await client.post("/v1/me/shelf", json={"register_numbers": []}, headers=me)
    ).status_code == 422
    many = [str(i) for i in range(101)]
    assert (
        await client.post("/v1/me/shelf", json={"register_numbers": many}, headers=me)
    ).status_code == 422
