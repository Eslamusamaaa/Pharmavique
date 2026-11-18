"""The read-only drug API (search and product lookup) on fakes: no database."""

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.search.application.handlers import SearchProductsHandler
from pharmavique.search.domain.documents import ProductKey, ProductToIndex, build_document
from pharmavique.search.infrastructure.memory import InMemorySearchIndex
from pharmavique.shared_kernel.market import Market


def card(
    number: str, name_en: str, name_ar: str | None, ingredient: str, **extra: str
) -> ProductCard:
    return ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=name_en,
        trade_name_ar=name_ar,
        ingredient_names=(ingredient,),
        dosage_form_en="Tablet",
        dosage_form_ar=None,
        marketing_company="ACME",
        manufacturers=(),
        atc_codes=(),
        listing_status=extra.get("status", "listed"),
        authorization_status=None,
        marketing_status=None,
    )


CARDS = [
    card("1-100", "PANADOL EXTRA TAB", "بانادول اكسترا", "PARACETAMOL"),
    card("1-200", "BRUFEN 400 MG TAB", "بروفين 400 ملجم", "IBUPROFEN"),
    card("1-300", "OLD DRUG", None, "ACMEDRONE", status="withdrawn"),
]


class FakeCatalog:
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(c for c in CARDS if c.register_number in register_numbers)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        raise NotImplementedError


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    index = InMemorySearchIndex()
    await index.upsert(
        [
            build_document(
                ProductToIndex(
                    key=ProductKey(c.market, c.register_number),
                    trade_name_en=c.trade_name_en,
                    trade_name_ar=c.trade_name_ar,
                    ingredient_names=c.ingredient_names,
                    marketing_company=c.marketing_company,
                    withdrawn=c.listing_status == "withdrawn",
                )
            )
            for c in CARDS
        ]
    )
    app = create_app(search=SearchProductsHandler(index), catalog=FakeCatalog())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_a_misspelled_name_returns_the_drug_with_its_card_and_why(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/search", params={"q": "panadool extra"})

    body = response.json()
    assert response.status_code == 200
    assert body["query"] == "panadool extra"
    top = body["results"][0]
    assert top["register_number"] == "1-100"
    assert top["trade_name_en"] == "PANADOL EXTRA TAB"
    assert top["trade_name_ar"] == "بانادول اكسترا"
    assert top["ingredients"] == ["PARACETAMOL"]
    assert top["reasons"][0]["signal"] == "fuzzy"
    assert top["exact"] is False
    # the score a person can read: the best similarity any signal found, from 0 to 1
    assert 0.3 < top["score"] <= 1.0
    assert top["score"] == max(r["score"] for r in top["reasons"])
    assert "not medical advice" in body["disclaimer"].lower()


async def test_a_register_number_is_an_exact_match(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/search", params={"q": "1-200"})).json()

    assert body["results"][0]["register_number"] == "1-200"
    assert body["results"][0]["exact"] is True
    assert body["results"][0]["score"] == 1.0


async def test_arabic_queries_work(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/search", params={"q": "بروفين"})).json()

    assert body["results"][0]["register_number"] == "1-200"


async def test_withdrawn_drugs_are_hidden_unless_asked_for(client: httpx.AsyncClient) -> None:
    hidden = (await client.get("/v1/search", params={"q": "old drug"})).json()
    shown = (
        await client.get("/v1/search", params={"q": "old drug", "include_withdrawn": "true"})
    ).json()

    assert "1-300" not in [r["register_number"] for r in hidden["results"]]
    assert shown["results"][0]["register_number"] == "1-300"
    assert shown["results"][0]["listing_status"] == "withdrawn"


async def test_nothing_found_is_an_empty_list_not_an_error(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/search", params={"q": "zzzzqqqq"})

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["count"] == 0


@pytest.mark.parametrize(
    "params",
    [{}, {"q": ""}, {"q": "x" * 201}, {"q": "panadol", "limit": 0}, {"q": "panadol", "limit": 51}],
)
async def test_bad_input_is_a_validation_error(
    client: httpx.AsyncClient, params: dict[str, str | int]
) -> None:
    assert (await client.get("/v1/search", params=params)).status_code == 422


async def test_a_product_can_be_read_by_its_register_number(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/products/1-100")

    assert response.status_code == 200
    assert response.json()["trade_name_en"] == "PANADOL EXTRA TAB"
    assert response.json()["marketing_company"] == "ACME"


async def test_an_unknown_product_is_a_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/products/9-999")).status_code == 404


async def test_without_a_database_the_data_endpoints_say_so_and_health_still_works() -> None:
    app = create_app()  # nothing injected and PHARMAVIQUE_DATABASE_URL not used
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/health")).status_code == 200
        response = await c.get("/v1/search", params={"q": "panadol"})

    assert response.status_code == 503
    assert "database" in response.json()["detail"].lower()


async def test_the_openapi_describes_the_new_endpoints(client: httpx.AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    assert "/v1/search" in paths
    assert "/v1/products/{register_number}" in paths
