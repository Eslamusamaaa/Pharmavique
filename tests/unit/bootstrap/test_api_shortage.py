"""Shortage endpoint: what SFDA lists, how sure the link is, and the same-ingredient products."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import (
    IngredientDetail,
    ListItem,
    PriceDetail,
    ProductCard,
    ProductDetails,
)
from pharmavique.shared_kernel.market import Market
from pharmavique.substitution.application.compare import CompareProductsHandler


def details(number: str, strength: str, price: str | None = "5.00") -> ProductDetails:
    card = ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=f"DRUG {number}",
        trade_name_ar=f"دواء {number}",
        ingredient_names=("PARACETAMOL",),
        dosage_form_en="Tablet",
        dosage_form_ar="قرص",
        marketing_company="ACME",
        manufacturers=("MAKER",),
        atc_codes=(),
        listing_status="listed",
        authorization_status="Valid",
        marketing_status="Marketed",
    )
    return ProductDetails(
        card=card,
        ingredients=(IngredientDetail("PARACETAMOL", strength, "mg"),),
        route_en=None,
        route_ar=None,
        package_type=None,
        package_size=None,
        legal_status=None,
        distribution_site=None,
        shelf_life=None,
        storage_en=None,
        storage_ar=None,
        marketing_company_country=None,
        manufacturers=(),
        price=PriceDetail(Decimal(price), "SAR", "owner_assumption") if price else None,
        source="sfda-drugs-list-web",
        source_ref="https://www.sfda.gov.sa/en/x",
        fetched_at=datetime(2026, 11, 17, tzinfo=UTC),
        trust="official",
    )


PRODUCTS = {
    "1": details("1", "500"),
    "2": details("2", "500", price="4.00"),
    "3": details("3", "500", price="3.00"),
    "4": details("4", "500"),
}


def row(list_name: str, availability: str, confidence: str = "matched") -> ListItem:
    return ListItem(
        list_name=list_name,
        confidence=confidence,
        reason="same substance and brand",
        cells=(("Generic Name", "PARACETAMOL"), ("Availability Status", availability)),
        detail=(("Trade name", "DRUG 1"), ("Trade name", "DRUG 1")),
        facets=(("availability", "unavailable" if list_name == "drug-shortage" else "resolved"),),
        link="/en/details_data?nid=1",
        source_ref="https://www.sfda.gov.sa/en/currentlyInShortageList?page=0",
        fetched_at=datetime(2026, 11, 18, tzinfo=UTC),
        trust="official",
    )


LISTED = {
    "1": [row("drug-shortage", "غير متوفر")],
    "3": [row("drug-shortage", "غير متوفر", confidence="possible")],
    "4": [row("drug-shortage-resolved", "تم الحل")],
}


class FakeDetails:
    async def get_details(self, market: Market, register_number: str) -> ProductDetails | None:
        return PRODUCTS.get(register_number)

    async def same_ingredients(
        self, market: Market, register_number: str, limit: int
    ) -> tuple[ProductDetails, ...]:
        return tuple(p for n, p in PRODUCTS.items() if n != register_number)[:limit]


class FakeListItems:
    async def list_items(
        self, market: Market, register_number: str, list_names: Sequence[str]
    ) -> tuple[ListItem, ...]:
        return tuple(i for i in LISTED.get(register_number, []) if i.list_name in list_names)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        details=FakeDetails(), equivalence=CompareProductsHandler(), list_items=FakeListItems()
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_a_drug_on_the_shortage_list_shows_the_record_and_same_ingredient_products(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/products/1/shortage")).json()

    assert body["status"] == "listed_in_shortage"
    item = body["items"][0]
    assert item["availability"] == "unavailable"
    assert item["confidence"] == "matched"
    assert item["trade_names"] == ["DRUG 1"]
    assert item["trust"] == "official"
    assert [s["register_number"] for s in body["substitutes"]] == ["3", "2", "4"]
    assert "pharmacist or doctor" in body["note"]
    assert "not medical advice" in body["disclaimer"].lower()


async def test_every_substitute_carries_the_computed_verdict_never_a_recommendation(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/products/1/shortage")).json()

    assert {s["verdict"] for s in body["substitutes"]} <= {
        "equivalent",
        "possible_needs_pharmacist_check",
        "not_equivalent",
    }
    note = body["note"].lower()
    assert "switch" not in note
    assert "stop" not in note


async def test_a_substitute_that_is_also_on_the_shortage_list_is_flagged(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/products/1/shortage")).json()

    flags = {s["register_number"]: s["also_on_shortage_list"] for s in body["substitutes"]}
    assert flags == {"2": False, "3": True, "4": False}  # 4 is only on the resolved list


async def test_a_possible_link_is_reported_as_possible(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/products/3/shortage")).json()

    assert body["status"] == "listed_in_shortage"
    assert body["items"][0]["confidence"] == "possible"


async def test_a_resolved_shortage_has_no_substitutes(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/products/4/shortage")).json()

    assert body["status"] == "resolved"
    assert body["substitutes"] == []


async def test_a_drug_with_no_record_says_that_is_not_a_stock_claim(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/products/2/shortage")).json()

    assert body["status"] == "not_listed"
    assert body["items"] == []
    assert "does not say it is in stock" in body["note"]


async def test_an_unknown_drug_is_a_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/products/9/shortage")).status_code == 404


async def test_without_a_database_the_shortage_endpoint_says_so() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/products/1/shortage")).status_code == 503
