"""The assistant shortage facts: only rows that name the product, then a coverage record."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from pharmavique.bootstrap.assistant_facts import ContractDrugFacts
from pharmavique.catalog.contracts.queries import CardPage, ListItem, ProductCard
from pharmavique.shared_kernel.market import Market

SOURCE = "https://www.sfda.gov.sa/en/details_data?nid=17594&id=X"


def card(register: str) -> ProductCard:
    return ProductCard(
        market=Market.SA,
        register_number=register,
        trade_name_en="Trulicity",
        trade_name_ar=None,
        ingredient_names=("DULAGLUTIDE",),
        dosage_form_en=None,
        dosage_form_ar=None,
        marketing_company=None,
        manufacturers=(),
        atc_codes=(),
        listing_status="listed",
        authorization_status=None,
        marketing_status=None,
    )


def row(list_name: str, confidence: str, availability: str = "unavailable") -> ListItem:
    return ListItem(
        list_name=list_name,
        confidence=confidence,
        reason="generic and trade name",
        cells=(),
        detail=(("Trade name", "TRULICITY 1.5 mg"),),
        facets=(("availability", availability),),
        link=None,
        source_ref=SOURCE,
        fetched_at=datetime(2026, 11, 23, tzinfo=UTC),
        trust="official",
    )


class FakeCatalog:
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(card(r) for r in register_numbers if r == "1")

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        return CardPage((), None)


class FakeListItems:
    def __init__(self, *items: ListItem) -> None:
        self.items = items

    async def list_items(
        self, market: Market, register_number: str, list_names: Sequence[str]
    ) -> tuple[ListItem, ...]:
        return self.items


def facts(*items: ListItem, available: bool = True) -> ContractDrugFacts:
    nothing = cast(Any, None)
    return ContractDrugFacts(
        nothing,
        FakeCatalog(),
        nothing,
        nothing,
        nothing,
        list_items=FakeListItems(*items) if available else None,
    )


async def test_a_row_that_names_the_product_is_a_shortage_with_its_list_and_source() -> None:
    rows = await facts(row("drug-shortage", "matched")).shortage("1")

    assert rows[0]["kind"] == "shortage"
    assert rows[0]["trade_names_on_the_list"] == ["TRULICITY 1.5 mg"]
    assert rows[0]["source_ref"] == SOURCE
    assert rows[-1] == {**rows[-1], "kind": "coverage", "status": "listed_in_shortage"}
    assert "nothing about stock at any pharmacy" in rows[-1]["note"].replace("says ", "")


async def test_a_row_that_names_only_the_ingredient_is_not_a_shortage_of_this_product() -> None:
    rows = await facts(row("drug-shortage", "possible")).shortage("1")

    assert [r["kind"] for r in rows] == ["coverage"]
    assert rows[0]["status"] == "not_listed"


async def test_a_resolved_row_is_reported_as_resolved() -> None:
    rows = await facts(row("drug-shortage-resolved", "matched", "resolved")).shortage("1")

    assert rows[0]["kind"] == "shortage_resolved"
    assert rows[-1]["status"] == "resolved"


async def test_the_same_row_is_shown_once() -> None:
    rows = await facts(row("drug-shortage", "matched"), row("drug-shortage", "matched")).shortage(
        "1"
    )

    assert [r["kind"] for r in rows] == ["shortage", "coverage"]


async def test_an_unknown_product_and_a_missing_source_are_errors_not_answers() -> None:
    with pytest.raises(ValueError, match="no product"):
        await facts().shortage("9")
    with pytest.raises(ValueError, match="not available"):
        await facts(available=False).shortage("1")
