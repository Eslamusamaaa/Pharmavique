"""The catalog's read side: product cards for other contexts."""

from collections.abc import Sequence

from pharmavique.catalog.application.ports import ProductReader, StoredProduct
from pharmavique.catalog.contracts.queries import MAX_EXPORT_PAGE, CardPage, ProductCard
from pharmavique.shared_kernel.market import Market


def card_of(stored: StoredProduct) -> ProductCard:
    data = stored.data
    return ProductCard(
        market=stored.id.market,
        register_number=stored.id.register_number,
        trade_name_en=data.trade_name.en,
        trade_name_ar=data.trade_name.ar,
        ingredient_names=tuple(line.name for line in data.ingredients),
        dosage_form_en=data.dosage_form.en,
        dosage_form_ar=data.dosage_form.ar,
        marketing_company=data.marketing_company.name if data.marketing_company else None,
        manufacturers=tuple(party.name for party in data.manufacturers),
        atc_codes=tuple(code.code for code in data.atc_codes),
        listing_status=stored.listing_status.value,
        authorization_status=data.authorization_status.raw if data.authorization_status else None,
        marketing_status=data.marketing_status.raw if data.marketing_status else None,
    )


class ReadProductCardsHandler:
    """Implements `CatalogQueries` over a `ProductReader`."""

    def __init__(self, reader: ProductReader) -> None:
        self._reader = reader

    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        found = await self._reader.get_many(market, register_numbers)
        return tuple(card_of(product) for product in found)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        if not 1 <= limit <= MAX_EXPORT_PAGE:
            raise ValueError(f"limit must be between 1 and {MAX_EXPORT_PAGE}")
        found = await self._reader.page(market, after, limit)
        cards = tuple(card_of(product) for product in found)
        # A full page may be the last one; the next call then returns an empty page and ends.
        next_after = cards[-1].register_number if len(cards) == limit else None
        return CardPage(cards=cards, next_after=next_after)
