"""POST /v1/interactions/check: products in, recorded interactions and duplicates out."""

from collections.abc import Collection, Sequence

import httpx

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.interactions.application.check import CheckInteractions
from pharmavique.interactions.domain.records import InteractionRecord
from pharmavique.interactions.domain.severity import Severity
from pharmavique.shared_kernel.market import Market


def card(register: str, name: str, *ingredients: str) -> ProductCard:
    return ProductCard(
        market=Market.SA,
        register_number=register,
        trade_name_en=name,
        trade_name_ar=None,
        ingredient_names=ingredients,
        dosage_form_en=None,
        dosage_form_ar=None,
        marketing_company=None,
        manufacturers=(),
        atc_codes=(),
        listing_status="listed",
        authorization_status=None,
        marketing_status=None,
    )


class FakeCatalog:
    def __init__(self, *cards: ProductCard) -> None:
        self.cards = {c.register_number: c for c in cards}

    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(self.cards[r] for r in register_numbers if r in self.cards)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        return CardPage(tuple(self.cards.values()), None)


class FakeStore:
    async def known(self, keys: Collection[str]) -> set[str]:
        return {"warfarin", "aspirin"} & set(keys)

    async def pairs_among(self, keys: Collection[str]) -> list[InteractionRecord]:
        return [InteractionRecord("aspirin", "warfarin", Severity.MAJOR, "ddinter-2.0")]


def client(*cards: ProductCard) -> httpx.AsyncClient:
    app = create_app(catalog=FakeCatalog(*cards), interactions=CheckInteractions(FakeStore()))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_two_products_with_a_recorded_pair_give_a_finding_with_the_source() -> None:
    async with client(
        card("1", "Coumadin", "WARFARIN SODIUM"), card("2", "Aspirin Protect", "ASPIRIN")
    ) as api:
        response = await api.post("/v1/interactions/check", json={"register_numbers": ["1", "2"]})

    body = response.json()
    assert response.status_code == 200
    assert body["findings"] == [
        {
            "kind": "interaction",
            "severity": "major",
            "registers": ["1", "2"],
            "ingredients": ["WARFARIN SODIUM", "ASPIRIN"],
            "source": "ddinter-2.0",
        }
    ]
    assert [p["register_number"] for p in body["products"]] == ["1", "2"]
    assert body["complete"] is False
    assert body["unknown_registers"] == []


async def test_unknown_register_numbers_are_named_not_silently_dropped() -> None:
    async with client(card("1", "Coumadin", "WARFARIN")) as api:
        response = await api.post("/v1/interactions/check", json={"register_numbers": ["1", "999"]})

    assert response.status_code == 200
    assert response.json()["unknown_registers"] == ["999"]


async def test_fewer_than_two_products_or_far_too_many_are_refused() -> None:
    async with client(card("1", "Coumadin", "WARFARIN")) as api:
        one = await api.post("/v1/interactions/check", json={"register_numbers": ["1"]})
        many = await api.post(
            "/v1/interactions/check", json={"register_numbers": [str(n) for n in range(40)]}
        )

    assert one.status_code == 422
    assert many.status_code == 422


async def test_without_a_database_the_endpoint_answers_503() -> None:
    app = create_app(catalog=FakeCatalog(), interactions=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        response = await api.post("/v1/interactions/check", json={"register_numbers": ["1", "2"]})

    assert response.status_code == 503
