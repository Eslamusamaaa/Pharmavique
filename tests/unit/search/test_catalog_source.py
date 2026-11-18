"""`search` reads the catalog's published cards and turns them into its own input type."""

from collections.abc import Sequence

from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.search.application.handlers import RebuildIndexHandler
from pharmavique.search.infrastructure.catalog_source import CatalogProductSource
from pharmavique.search.infrastructure.memory import InMemorySearchIndex
from pharmavique.shared_kernel.market import Market


def card(number: str, status: str = "listed") -> ProductCard:
    return ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=f"DRUG{number}",
        trade_name_ar="دواء",
        ingredient_names=("ACMEDRONE", "OTHERDRONE"),
        dosage_form_en="Tablet",
        dosage_form_ar=None,
        marketing_company="ACME",
        manufacturers=(),
        atc_codes=(),
        listing_status=status,
        authorization_status=None,
        marketing_status=None,
    )


class FakeCatalog:
    def __init__(self, cards: Sequence[ProductCard]) -> None:
        self.cards = sorted(cards, key=lambda c: c.register_number)
        self.calls = 0

    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(c for c in self.cards if c.register_number in register_numbers)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        self.calls += 1
        rest = [c for c in self.cards if after is None or c.register_number > after]
        page = tuple(rest[:limit])
        return CardPage(page, page[-1].register_number if len(page) == limit else None)


async def test_every_card_of_every_page_becomes_a_product_to_index() -> None:
    catalog = FakeCatalog([card(str(n)) for n in range(1, 6)])

    pages = [page async for page in CatalogProductSource(catalog).pages(Market.SA, 2)]

    assert [len(p) for p in pages] == [2, 2, 1]
    first = pages[0][0]
    assert (first.key.register_number, first.trade_name_en) == ("1", "DRUG1")
    assert first.ingredient_names == ("ACMEDRONE", "OTHERDRONE")
    assert first.marketing_company == "ACME"


async def test_a_withdrawn_card_is_marked_withdrawn() -> None:
    catalog = FakeCatalog([card("1"), card("2", "withdrawn")])

    (page,) = [p async for p in CatalogProductSource(catalog).pages(Market.SA, 10)]

    assert [p.withdrawn for p in page] == [False, True]


async def test_an_empty_catalog_gives_no_pages() -> None:
    assert [p async for p in CatalogProductSource(FakeCatalog([])).pages(Market.SA, 10)] == []


async def test_rebuilding_from_the_catalog_fills_the_index() -> None:
    index = InMemorySearchIndex()
    source = CatalogProductSource(FakeCatalog([card(str(n)) for n in range(1, 8)]))

    count = await RebuildIndexHandler(source, index, page_size=3).rebuild(Market.SA)

    assert count == 7
    assert len(index) == 7
