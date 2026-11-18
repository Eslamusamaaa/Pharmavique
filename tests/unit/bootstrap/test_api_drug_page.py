"""The drug page endpoints (B8): full details with provenance, and same-ingredient products."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import (
    IngredientDetail,
    Maker,
    PriceDetail,
    ProductCard,
    ProductDetails,
)
from pharmavique.shared_kernel.market import Market
from pharmavique.substitution.application.compare import CompareProductsHandler


def details(
    number: str, strength: str, form: str = "Tablet", price: str | None = "7.25"
) -> ProductDetails:
    card = ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=f"DRUG {number}",
        trade_name_ar=f"دواء {number}",
        ingredient_names=("PARACETAMOL",),
        dosage_form_en=form,
        dosage_form_ar="قرص",
        marketing_company="ACME",
        manufacturers=("MAKER",),
        atc_codes=("N02BE01",),
        listing_status="listed",
        authorization_status="Valid",
        marketing_status="Marketed",
    )
    return ProductDetails(
        card=card,
        ingredients=(IngredientDetail("PARACETAMOL", strength, "mg"),),
        route_en="Oral use",
        route_ar="عن طريق الفم",
        package_type="Blister",
        package_size=24,
        legal_status="OTC",
        distribution_site="Pharmacy",
        shelf_life="48",
        storage_en="store below 30°c",
        storage_ar="يحفظ تحت 30",
        marketing_company_country="Ireland",
        manufacturers=(Maker("MAKER", "Saudi Arabia"),),
        price=PriceDetail(Decimal(price), "SAR", "owner_assumption") if price else None,
        source="sfda-drugs-list-web",
        source_ref="https://www.sfda.gov.sa/en/x",
        fetched_at=datetime(2026, 11, 17, 7, 56, tzinfo=UTC),
        trust="official",
    )


PRODUCTS = {
    "1": details("1", "500"),
    "2": details("2", "500", price="5.50"),
    "3": details("3", "650", price="4.00"),
    "4": details("4", "500", form="Effervescent tablet", price=None),
}


class FakeDetails:
    async def get_details(self, market: Market, register_number: str) -> ProductDetails | None:
        return PRODUCTS.get(register_number)

    async def same_ingredients(
        self, market: Market, register_number: str, limit: int
    ) -> tuple[ProductDetails, ...]:
        return tuple(p for n, p in PRODUCTS.items() if n != register_number)[:limit]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(details=FakeDetails(), equivalence=CompareProductsHandler())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_the_drug_page_has_every_field_with_its_source(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/products/1/details")

    body = response.json()
    assert response.status_code == 200
    assert body["trade_name_ar"] == "دواء 1"
    assert body["ingredients"] == [{"name": "PARACETAMOL", "strength": "500", "unit": "mg"}]
    assert body["route_ar"] == "عن طريق الفم"
    assert body["atc_codes"] == ["N02BE01"]
    assert body["shelf_life"] == "48"
    assert body["manufacturers"] == [{"name": "MAKER", "country": "Saudi Arabia"}]
    assert body["price"] == {
        "amount": "7.25",
        "currency_code": "SAR",
        "currency_basis": "owner_assumption",
    }
    assert body["provenance"]["trust"] == "official"
    assert body["provenance"]["source_ref"] == "https://www.sfda.gov.sa/en/x"
    assert "not medical advice" in body["disclaimer"].lower()


async def test_an_unknown_drug_page_is_a_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/products/9/details")).status_code == 404


async def test_same_ingredient_products_carry_the_computed_verdict_cheapest_first(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/products/1/same-ingredient")).json()

    rows = [(r["register_number"], r["verdict"]) for r in body["results"]]
    assert rows == [
        ("3", "not_equivalent"),
        ("2", "equivalent"),
        ("4", "possible_needs_pharmacist_check"),
    ]
    assert body["results"][1]["price"]["amount"] == "5.50"
    assert body["results"][2]["price"] is None


async def test_without_a_database_the_drug_page_says_so() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/products/1/details")).status_code == 503
