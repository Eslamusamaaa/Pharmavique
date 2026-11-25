"""Similar-name warnings on the drug page: informational, never advice."""

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

from pharmavique.bootstrap.api import create_app
from pharmavique.catalog.contracts.queries import CardPage, ProductCard, TradeName
from pharmavique.search.application.ports import ProductNames, StoredSimilarNames
from pharmavique.search.application.similar_names import WINDOW, build_indexes
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
    card("6", "PANADOLIN TAB", None, "SOMETHING ELSE"),  # only spelled alike: a weaker match
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


async def test_only_the_strong_matches_are_shown_unless_the_weaker_ones_are_asked_for(
    client: httpx.AsyncClient,
) -> None:
    default = (await client.get("/v1/products/1/similar-names")).json()
    everything = (await client.get("/v1/products/1/similar-names?include_weaker=true")).json()

    assert {r["register_number"] for r in default["results"]} == {"2", "3"}
    assert {r["level"] for r in default["results"]} == {"high"}
    assert default["shown_level"] == "high"
    assert default["hidden_weaker"] == 1  # PANADOLIN is only spelled alike: counted, not shown

    assert {r["register_number"] for r in everything["results"]} == {"2", "3", "6"}
    assert everything["shown_level"] == "all"
    assert everything["hidden_weaker"] == 0
    weaker = next(r for r in everything["results"] if r["register_number"] == "6")
    assert weaker["level"] == "medium"


async def test_a_drug_whose_only_look_alikes_are_weak_shows_none_by_default(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/products/6/similar-names")).json()
    assert body["results"] == []
    assert body["count"] == 0
    assert body["hidden_weaker"] >= 1


async def test_the_limit_applies_to_what_is_shown_not_to_what_is_hidden(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/v1/products/1/similar-names?limit=1")).json()
    assert body["count"] == 1
    assert body["hidden_weaker"] == 1


class FakeNames:
    def __init__(self) -> None:
        self.calls = 0

    async def trade_names(self, market: Market) -> tuple[TradeName, ...]:
        self.calls += 1
        return tuple(TradeName(c.register_number, c.trade_name_en, c.trade_name_ar) for c in CARDS)


class NoExport(FakeCatalog):
    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        raise AssertionError("the index reads the names only, not every product in full")


async def test_the_index_is_built_from_the_names_alone_when_they_can_be_read_alone() -> None:
    # Reading all 9,186 products in full took most of the 3.1 s of the first answer on Vercel.
    names = FakeNames()
    app = create_app(catalog=NoExport())
    app.state.catalog_names = names
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        body = (await c.get("/v1/products/1/similar-names")).json()
        await c.get("/v1/products/4/similar-names")

    assert "2" in {r["register_number"] for r in body["results"]}
    assert names.calls == 1


class StoredNames:
    """What the daily refresh stored, built with the same index the API would build."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        names = [ProductNames(c.register_number, c.trade_name_en, c.trade_name_ar) for c in CARDS]
        english, arabic = build_indexes(names)
        self.rows = {
            n.register_number: StoredSimilarNames(
                n.register_number,
                english.similar_to(n.register_number, WINDOW),
                arabic.similar_to(n.register_number, WINDOW),
            )
            for n in names
        }

    async def replace(self, market: Market, rows: Sequence[StoredSimilarNames]) -> None:
        raise NotImplementedError

    async def find(self, market: Market, register_number: str) -> StoredSimilarNames | None:
        if self.fail:
            raise RuntimeError("relation search.similar_name does not exist")
        return self.rows.get(register_number)


async def test_a_stored_answer_is_served_without_building_the_index() -> None:
    expected_app = create_app(catalog=FakeCatalog())
    app = create_app(catalog=NoExport())  # building the index would fail the request
    app.state.similar_names = StoredNames()
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=expected_app), base_url="http://t"
        ) as reference,
    ):
        for number in ("1", "4", "5"):
            path = f"/v1/products/{number}/similar-names?include_weaker=true"
            assert (await c.get(path)).json() == (await reference.get(path)).json(), number


async def test_a_product_the_rebuild_has_not_seen_or_a_failing_store_falls_back_to_the_index() -> (
    None
):
    for store in (StoredNames(fail=True), StoredNames()):
        store.rows.pop("1", None)
        app = create_app(catalog=FakeCatalog())
        app.state.similar_names = store
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            body = (await c.get("/v1/products/1/similar-names")).json()
        assert "2" in {r["register_number"] for r in body["results"]}
