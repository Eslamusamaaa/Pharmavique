"""Where `search` gets its products: the catalog's published product cards.

This is the only place in `search` that knows the catalog's contract. It turns each card into
`search`'s own input type, so nothing else in the context depends on the catalog.
"""

from collections.abc import AsyncIterator, Sequence

from pharmavique.catalog.contracts.queries import CatalogNames, CatalogQueries, ProductCard
from pharmavique.search.application.ports import ProductNames
from pharmavique.search.domain.documents import ProductKey, ProductToIndex
from pharmavique.shared_kernel.market import Market


def to_product_to_index(card: ProductCard) -> ProductToIndex:
    return ProductToIndex(
        key=ProductKey(card.market, card.register_number),
        trade_name_en=card.trade_name_en,
        trade_name_ar=card.trade_name_ar,
        ingredient_names=card.ingredient_names,
        marketing_company=card.marketing_company,
        withdrawn=card.listing_status == "withdrawn",
    )


class CatalogProductSource:
    """Implements the `ProductSource` port over `CatalogQueries.export_cards`."""

    def __init__(self, queries: CatalogQueries) -> None:
        self._queries = queries

    async def pages(
        self, market: Market, page_size: int
    ) -> AsyncIterator[Sequence[ProductToIndex]]:
        after: str | None = None
        while True:
            page = await self._queries.export_cards(market, after, page_size)
            if page.cards:
                yield [to_product_to_index(card) for card in page.cards]
            if page.next_after is None:
                return
            after = page.next_after


class CatalogNameSource:
    """Implements the `NameSource` port over `CatalogNames.trade_names` (names only)."""

    def __init__(self, names: CatalogNames) -> None:
        self._names = names

    async def names(self, market: Market) -> Sequence[ProductNames]:
        return [
            ProductNames(n.register_number, n.en, n.ar)
            for n in await self._names.trade_names(market)
        ]
