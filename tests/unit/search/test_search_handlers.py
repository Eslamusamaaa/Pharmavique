"""Search use cases on the in-memory index: no database, no catalog, no framework."""

from collections.abc import AsyncIterator, Sequence

import pytest

from pharmavique.search.application.handlers import RebuildIndexHandler, SearchProductsHandler
from pharmavique.search.contracts.queries import SearchQuery
from pharmavique.search.domain.documents import ProductKey, ProductToIndex, build_document
from pharmavique.search.infrastructure.memory import InMemorySearchIndex
from pharmavique.shared_kernel.market import Market


def product(
    number: str,
    name_en: str | None,
    name_ar: str | None = None,
    ingredients: tuple[str, ...] = (),
    withdrawn: bool = False,
) -> ProductToIndex:
    return ProductToIndex(
        key=ProductKey(Market.SA, number),
        trade_name_en=name_en,
        trade_name_ar=name_ar,
        ingredient_names=ingredients,
        marketing_company=None,
        withdrawn=withdrawn,
    )


async def index_of(*products: ProductToIndex) -> InMemorySearchIndex:
    index = InMemorySearchIndex()
    await index.upsert([build_document(p) for p in products])
    return index


def query(text: str, **overrides: object) -> SearchQuery:
    return SearchQuery(text=text, market=Market.SA, **overrides)  # type: ignore[arg-type]


CATALOG = (
    product("1-100", "PANADOL", "بانادول", ("PARACETAMOL",)),
    product("1-200", "PANTOLOC", "بانتولوك", ("PANTOPRAZOLE",)),
    product("1-300", "AUGMENTIN", "اوجمنتين", ("AMOXICILLIN", "CLAVULANIC ACID")),
    product("1-400", "OLD DRUG", None, ("ACMEDRONE",), withdrawn=True),
)


async def test_a_misspelled_name_still_finds_the_product_and_says_why() -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    result = await handler.search(query("panadool"))

    top = result.matches[0]
    assert top.register_number == "1-100"
    assert [(r.signal, r.rank) for r in top.reasons] == [("fuzzy", 1)]
    assert not top.exact


async def test_arabic_with_diacritics_and_letter_variants_finds_the_same_product() -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    result = await handler.search(query("بَانَادُول"))

    assert result.matches[0].register_number == "1-100"


async def test_the_register_number_is_an_exact_match_and_comes_first() -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    result = await handler.search(query(" 1-300 "))

    assert result.matches[0].register_number == "1-300"
    assert result.matches[0].exact
    assert result.matches[0].reasons[0].signal == "exact"


async def test_an_ingredient_name_finds_products_that_contain_it() -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    result = await handler.search(query("amoxicillin"))

    assert result.matches[0].register_number == "1-300"


async def test_withdrawn_products_are_hidden_unless_asked_for() -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    hidden = await handler.search(query("old drug"))
    shown = await handler.search(query("old drug", include_withdrawn=True))

    assert "1-400" not in [m.register_number for m in hidden.matches]
    assert shown.matches[0].register_number == "1-400"


async def test_text_that_resembles_nothing_returns_nothing() -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    assert (await handler.search(query("zzzzqqqq"))).matches == ()
    assert (await handler.search(query("   "))).matches == ()


async def test_the_limit_cuts_the_list() -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    result = await handler.search(query("pan", limit=1))

    assert len(result.matches) == 1


async def test_a_query_for_another_market_finds_nothing() -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    result = await handler.search(SearchQuery(text="panadol", market=Market.EG))

    assert result.matches == ()


@pytest.mark.parametrize("limit", [0, -3])
async def test_a_nonpositive_limit_is_refused(limit: int) -> None:
    handler = SearchProductsHandler(await index_of(*CATALOG))

    with pytest.raises(ValueError, match="limit"):
        await handler.search(query("panadol", limit=limit))


class PagedSource:
    def __init__(self, products: Sequence[ProductToIndex]) -> None:
        self.products = products
        self.page_sizes: list[int] = []

    async def pages(
        self, market: Market, page_size: int
    ) -> AsyncIterator[Sequence[ProductToIndex]]:
        self.page_sizes.append(page_size)
        for start in range(0, len(self.products), page_size):
            yield self.products[start : start + page_size]


async def test_rebuild_indexes_every_page_and_can_be_repeated() -> None:
    index = InMemorySearchIndex()
    source = PagedSource(CATALOG)
    rebuild = RebuildIndexHandler(source, index, page_size=3)

    first = await rebuild.rebuild(Market.SA)
    second = await rebuild.rebuild(Market.SA)

    assert first == second == len(CATALOG)
    assert source.page_sizes == [3, 3]
    assert len(index) == len(CATALOG)
