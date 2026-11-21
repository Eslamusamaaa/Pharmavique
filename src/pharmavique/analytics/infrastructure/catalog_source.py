"""Where `analytics` gets its products: the catalog's published full export.

The only place in `analytics` that knows the catalog's contract; it turns each product into the
context's own `MarketProduct`.
"""

from collections.abc import AsyncIterator, Sequence

from pharmavique.analytics.domain.market import IngredientLine, MarketProduct
from pharmavique.catalog.contracts.queries import CatalogDetailsExport, ProductDetails
from pharmavique.shared_kernel.market import Market


def to_market_product(details: ProductDetails) -> MarketProduct:
    card = details.card
    return MarketProduct(
        market=card.market.value,
        register_number=card.register_number,
        trade_name_en=card.trade_name_en,
        trade_name_ar=card.trade_name_ar,
        ingredients=tuple(IngredientLine(i.name, i.strength, i.unit) for i in details.ingredients),
        dosage_form=card.dosage_form_en or card.dosage_form_ar,
        marketing_company=card.marketing_company,
        listing_status=card.listing_status,
        price_amount=details.price.amount if details.price else None,
        price_currency_code=details.price.currency_code if details.price else None,
        price_currency_basis=details.price.currency_basis if details.price else None,
    )


class CatalogMarketSource:
    """Implements the `MarketSource` port over `CatalogDetailsExport.export_details`."""

    def __init__(self, export: CatalogDetailsExport) -> None:
        self._export = export

    async def pages(self, market: Market, page_size: int) -> AsyncIterator[Sequence[MarketProduct]]:
        after: str | None = None
        while True:
            page = await self._export.export_details(market, after, page_size)
            if page.items:
                yield [to_market_product(item) for item in page.items]
            if page.next_after is None:
                return
            after = page.next_after
