"""Similar-name warnings on the drug page: informational, never advice."""

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.shared_kernel.market import Market


def card(number: str, en: str, ar: str | None, ingredient: str) -> ProductCard:
    return ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=en,
        trade_name_ar=ar,
        ingredient_names=(ingredient,),
        dosage_form_en="Tablet",
        dosage_form_ar="قرص",
        marketing_company="ACME",
        manufacturers=(),
        atc_codes=(),
        listing_status="listed",
        authorization_status=None,
        marketing_status=None,
    )


CARDS = [
    card("1", "PANADOL 500 MG TABLET", "بنادول", "PARACETAMOL"),
    card("2", "PANADOLE 250 MG TAB", "بنادوول", "PARACETAMOL"),
    card("3", "BANADOL 10 MG TAB", None, "SOMETHING ELSE"),
    card("4", "AUGMENTIN 625 MG TAB", "اوجمنتين", "AMOXICILLIN"),
    card("5", "PANADOL EXTRA TAB", None, "PARACETAMOL,CAFFEINE"),
]


class FakeCatalog:
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(c for c in CARDS if c.register_number in register_numbers)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        rest = [c for c in CARDS if after is None or c.register_number > after]
        page = rest[:limit]
        more = len(rest) > limit
        return CardPage(tuple(page), page[-1].register_number if more else None)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(catalog=FakeCatalog())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_similar_names_are_listed_with_why_and_whether_the_ingredients_match(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/products/1/similar-names")).json()

    rows = {r["register_number"]: r for r in body["results"]}
    assert set(rows) == {"2", "3"}  # not AUGMENTIN, not the same family "PANADOL EXTRA"
    assert rows["2"]["same_ingredients"] is True
    assert rows["3"]["same_ingredients"] is False
    assert "sounds_alike" in rows["3"]["reasons"]
    assert body["reviewed"] is False
    assert "double-check" in body["note"].lower()
    assert "not medical advice" in body["disclaimer"].lower()


async def test_arabic_names_find_arabic_look_alikes(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/products/1/similar-names")).json()

    assert any("ar" in r["scripts"] and r["register_number"] == "2" for r in body["results"])


async def test_a_drug_without_look_alikes_has_an_empty_list(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/products/4/similar-names")).json()

    assert body["results"] == []


async def test_an_unknown_drug_is_a_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/products/9/similar-names")).status_code == 404


async def test_without_a_database_the_endpoint_says_so() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/v1/products/1/similar-names")).status_code == 503
