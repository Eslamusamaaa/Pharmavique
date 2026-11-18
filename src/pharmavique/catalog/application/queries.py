"""The catalog's read side: product cards for other contexts."""

from collections.abc import Sequence

from pharmavique.catalog.application.ports import ProductReader, StoredProduct
from pharmavique.catalog.contracts.queries import (
    MAX_EXPORT_PAGE,
    CardPage,
    IngredientDetail,
    Maker,
    PriceDetail,
    ProductCard,
    ProductDetails,
)
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


def details_of(stored: StoredProduct) -> ProductDetails:
    data = stored.data
    price = data.price
    provenance = stored.provenance
    return ProductDetails(
        card=card_of(stored),
        ingredients=tuple(
            IngredientDetail(
                line.name,
                format(line.strength, "f") if line.strength is not None else None,
                line.unit,
            )
            for line in data.ingredients
        ),
        route_en=data.route.en if data.route else None,
        route_ar=data.route.ar if data.route else None,
        package_type=data.package.package_type,
        package_size=data.package.package_size,
        legal_status=data.legal_status.raw if data.legal_status else None,
        distribution_site=data.distribution_site.raw if data.distribution_site else None,
        shelf_life=data.shelf_life,
        storage_en=data.storage_conditions.en if data.storage_conditions else None,
        storage_ar=data.storage_conditions.ar if data.storage_conditions else None,
        marketing_company_country=(
            data.marketing_company.country if data.marketing_company else None
        ),
        manufacturers=tuple(Maker(p.name, p.country) for p in data.manufacturers),
        price=(
            PriceDetail(price.amount, price.currency.code, price.currency.basis.value)
            if price is not None
            else None
        ),
        source=provenance.source if provenance else None,
        source_ref=provenance.source_ref if provenance else None,
        fetched_at=provenance.fetched_at if provenance else None,
        trust=provenance.trust.value if provenance else None,
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

    async def get_details(self, market: Market, register_number: str) -> ProductDetails | None:
        found = await self._reader.get_many(market, [register_number])
        return details_of(found[0]) if found else None

    async def same_ingredients(
        self, market: Market, register_number: str, limit: int
    ) -> tuple[ProductDetails, ...]:
        found = await self._reader.get_many(market, [register_number])
        if not found:
            return ()
        names = [line.name for line in found[0].data.ingredients]
        others = await self._reader.with_ingredient_set(market, names, limit + 1)
        return tuple(details_of(p) for p in others if p.id.register_number != register_number)[
            :limit
        ]
