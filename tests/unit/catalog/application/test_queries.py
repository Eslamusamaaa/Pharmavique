"""The catalog's read side for other contexts: product cards, fetched or exported in pages."""

from collections.abc import Sequence
from decimal import Decimal

import pytest

from pharmavique.catalog.application.ports import StoredProduct
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.domain.product import ListingStatus, ProductData
from pharmavique.catalog.domain.values import (
    CodedValue,
    IngredientLine,
    LocalizedText,
    Party,
    ProductId,
)
from pharmavique.shared_kernel.market import Market


def stored(
    number: str, status: ListingStatus = ListingStatus.LISTED, **data: object
) -> StoredProduct:
    fields: dict[str, object] = {
        "trade_name": LocalizedText(f"TRADE-{number}", f"تجاري-{number}"),
        "ingredients": (IngredientLine("ACMEDRONE", Decimal("5"), "mg"),),
        "dosage_form": LocalizedText("Tablet", None),
    }
    fields.update(data)
    return StoredProduct(
        id=ProductId(Market.SA, number),
        data=ProductData(**fields),  # type: ignore[arg-type]
        listing_status=status,
    )


class FakeReader:
    def __init__(self, *products: StoredProduct) -> None:
        self.products = sorted(products, key=lambda p: p.id.register_number)

    async def get_many(
        self, market: Market, register_numbers: Sequence[str]
    ) -> list[StoredProduct]:
        wanted = set(register_numbers)
        return [
            p for p in self.products if p.id.market is market and p.id.register_number in wanted
        ]

    async def page(self, market: Market, after: str | None, limit: int) -> list[StoredProduct]:
        rows = [
            p
            for p in self.products
            if p.id.market is market and (after is None or p.id.register_number > after)
        ]
        return rows[:limit]

    async def with_ingredient_set(
        self, market: Market, names: Sequence[str], limit: int
    ) -> list[StoredProduct]:
        return []


async def test_a_card_carries_the_names_ingredients_and_status_search_needs() -> None:
    product = stored(
        "1-1",
        marketing_company=Party("ACME PHARMA", "Saudi Arabia"),
        manufacturers=(Party("MAKER LTD"),),
        marketing_status=CodedValue("Marketed", "marketed"),
        authorization_status=CodedValue("Valid", "valid"),
    )
    handler = ReadProductCardsHandler(FakeReader(product))

    (card,) = await handler.get_cards(Market.SA, ("1-1",))

    assert (card.market, card.register_number) == (Market.SA, "1-1")
    assert (card.trade_name_en, card.trade_name_ar) == ("TRADE-1-1", "تجاري-1-1")
    assert card.ingredient_names == ("ACMEDRONE",)
    assert card.dosage_form_en == "Tablet"
    assert card.marketing_company == "ACME PHARMA"
    assert card.manufacturers == ("MAKER LTD",)
    assert card.listing_status == "listed"
    assert (card.authorization_status, card.marketing_status) == ("Valid", "Marketed")


async def test_unknown_register_numbers_are_left_out_not_invented() -> None:
    handler = ReadProductCardsHandler(FakeReader(stored("1-1")))

    cards = await handler.get_cards(Market.SA, ("1-1", "9-9"))

    assert [c.register_number for c in cards] == ["1-1"]


async def test_withdrawn_products_are_still_returned_with_their_status() -> None:
    handler = ReadProductCardsHandler(FakeReader(stored("1-1", ListingStatus.WITHDRAWN)))

    (card,) = await handler.get_cards(Market.SA, ("1-1",))

    assert card.listing_status == "withdrawn"


async def test_export_walks_every_product_once_in_register_number_order() -> None:
    handler = ReadProductCardsHandler(FakeReader(*(stored(f"1-{n}") for n in range(1, 8))))

    seen: list[str] = []
    after = None
    pages = 0
    while True:
        page = await handler.export_cards(Market.SA, after, limit=3)
        seen += [c.register_number for c in page.cards]
        pages += 1
        if page.next_after is None:
            break
        after = page.next_after

    assert seen == [f"1-{n}" for n in range(1, 8)]
    assert pages == 3


async def test_an_exact_multiple_of_the_page_size_ends_with_an_empty_page() -> None:
    handler = ReadProductCardsHandler(FakeReader(stored("1-1"), stored("1-2")))

    first = await handler.export_cards(Market.SA, None, limit=2)
    second = await handler.export_cards(Market.SA, first.next_after, limit=2)

    assert first.next_after == "1-2"
    assert second.cards == ()
    assert second.next_after is None


@pytest.mark.parametrize("limit", [0, -1, 10_001])
async def test_a_page_size_outside_the_allowed_range_is_refused(limit: int) -> None:
    handler = ReadProductCardsHandler(FakeReader())

    with pytest.raises(ValueError, match="limit"):
        await handler.export_cards(Market.SA, None, limit=limit)
