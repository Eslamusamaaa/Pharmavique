"""Compare two drugs side by side: facts from the catalog, verdict from the substitution rules."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import (
    IngredientDetail,
    PriceDetail,
    ProductCard,
    ProductDetails,
)
from pharmavique.shared_kernel.market import Market
from pharmavique.substitution.application.compare import CompareProductsHandler


def details(
    number: str,
    strength: str = "500",
    form: str = "Tablet",
    company: str = "ACME",
    price: str | None = "5.00",
    ingredient: str = "PARACETAMOL",
) -> ProductDetails:
    card = ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=f"DRUG {number}",
        trade_name_ar=f"دواء {number}",
        ingredient_names=(ingredient,),
        dosage_form_en=form,
        dosage_form_ar="قرص",
        marketing_company=company,
        manufacturers=("MAKER",),
        atc_codes=(),
        listing_status="listed",
        authorization_status="Valid",
        marketing_status="Marketed",
        legal_status="OTC",
    )
    return ProductDetails(
        card=card,
        ingredients=(IngredientDetail(ingredient, strength, "mg"),),
        route_en="Oral use",
        route_ar=None,
        package_type=None,
        package_size=None,
        legal_status="OTC",
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
    "1": details("1"),
    "2": details("2", company="OTHER", price="4.00"),
    "3": details("3", strength="650"),
    "4": details("4", ingredient="IBUPROFEN"),
    "5": details("5", form="Effervescent tablet"),
}


class FakeDetails:
    async def get_details(self, market: Market, register_number: str) -> ProductDetails | None:
        return PRODUCTS.get(register_number)

    async def same_ingredients(
        self, market: Market, register_number: str, limit: int
    ) -> tuple[ProductDetails, ...]:
        return ()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(details=FakeDetails(), equivalence=CompareProductsHandler())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_two_drugs_with_the_same_ingredient_strength_and_form_are_equivalent(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/compare", params={"a": "1", "b": "2"})).json()

    assert body["verdict"] == "equivalent"
    assert body["a"]["register_number"] == "1"
    assert body["b"]["price"]["amount"] == "4"
    assert body["differences"] == ["marketing_company", "price"]
    assert "not medical advice" in body["disclaimer"].lower()


async def test_a_different_strength_is_not_equivalent_and_listed_as_a_difference(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/compare", params={"a": "1", "b": "3"})).json()

    assert body["verdict"] == "not_equivalent"
    assert "ingredients" in body["differences"]


async def test_a_different_ingredient_is_never_equivalent(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/compare", params={"a": "1", "b": "4"})).json()

    assert body["verdict"] == "not_equivalent"
    assert "ingredients" in body["differences"]


async def test_a_differently_written_form_needs_a_pharmacist_check(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/compare", params={"a": "1", "b": "5"})).json()

    assert body["verdict"] == "possible_needs_pharmacist_check"
    assert "dosage_form" in body["differences"]


async def test_the_same_drug_twice_is_a_400(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/compare", params={"a": "1", "b": "1"})).status_code == 400


async def test_an_unknown_drug_is_a_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/compare", params={"a": "1", "b": "9"})).status_code == 404


async def test_without_a_database_compare_says_so() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/compare", params={"a": "1", "b": "2"})).status_code == 503
