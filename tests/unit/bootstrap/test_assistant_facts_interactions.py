"""The assistant's interaction facts: findings with sources, then always a coverage record."""

from collections.abc import Collection, Sequence
from typing import Any, cast

import pytest

from pharmavique.bootstrap.assistant_facts import ContractDrugFacts
from pharmavique.catalog.contracts.queries import CardPage, ProductCard
from pharmavique.interactions.application.check import CheckInteractions
from pharmavique.interactions.domain.records import InteractionRecord
from pharmavique.interactions.domain.severity import Severity
from pharmavique.shared_kernel.market import Market


def card(register: str, name: str, *ingredients: str) -> ProductCard:
    return ProductCard(
        market=Market.SA,
        register_number=register,
        trade_name_en=name,
        trade_name_ar=None,
        ingredient_names=ingredients,
        dosage_form_en=None,
        dosage_form_ar=None,
        marketing_company=None,
        manufacturers=(),
        atc_codes=(),
        listing_status="listed",
        authorization_status=None,
        marketing_status=None,
    )


class FakeCatalog:
    def __init__(self, *cards: ProductCard) -> None:
        self.cards = {c.register_number: c for c in cards}

    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(self.cards[r] for r in register_numbers if r in self.cards)

    async def export_cards(self, market: Market, after: str | None, limit: int) -> CardPage:
        return CardPage(tuple(self.cards.values()), None)


class FakeStore:
    async def known(self, keys: Collection[str]) -> set[str]:
        return {"warfarin", "aspirin"} & set(keys)

    async def pairs_among(self, keys: Collection[str]) -> list[InteractionRecord]:
        return [InteractionRecord("aspirin", "warfarin", Severity.MAJOR, "ddinter-2.0")]


def facts(*cards: ProductCard, with_interactions: bool = True) -> ContractDrugFacts:
    nothing = cast(Any, None)
    return ContractDrugFacts(
        nothing,
        FakeCatalog(*cards),
        nothing,
        nothing,
        nothing,
        interactions=CheckInteractions(FakeStore()) if with_interactions else None,
    )


async def test_a_finding_names_both_products_the_severity_and_the_source_then_coverage() -> None:
    rows = await facts(
        card("1", "Coumadin", "WARFARIN SODIUM"), card("2", "Aspirin Protect", "ASPIRIN")
    ).check_interactions(["1", "2"])

    assert rows[0]["kind"] == "interaction"
    assert rows[0]["severity"] == "major"
    assert rows[0]["drugs"] == ["Coumadin", "Aspirin Protect"]
    assert rows[0]["source"] == "ddinter-2.0"
    assert rows[-1]["kind"] == "coverage"
    assert "never a safety verdict" in rows[-1]["note"]


async def test_nothing_found_still_returns_a_coverage_record_that_lists_what_was_not_judged() -> (
    None
):
    rows = await facts(
        card("1", "Coumadin", "WARFARIN"), card("2", "Newdrug", "ZZZ-NEW-MOLECULE")
    ).check_interactions(["1", "2", "999"])

    (coverage,) = [r for r in rows if r["kind"] == "coverage"]
    assert [r["kind"] for r in rows] == ["coverage"]
    assert coverage["not_covered"] == [{"register_number": "2", "ingredient": "ZZZ-NEW-MOLECULE"}]
    assert coverage["not_found_register_numbers"] == ["999"]


async def test_without_the_interaction_source_the_tool_says_so() -> None:
    with pytest.raises(ValueError, match="not available"):
        await facts(with_interactions=False).check_interactions(["1", "2"])


class FakeSearch:
    async def search(self, query: Any) -> Any:
        from pharmavique.search.contracts.queries import SearchMatch, SearchResult

        return SearchResult(
            (
                SearchMatch(Market.SA, "1", 0.9, True, ()),
                SearchMatch(Market.SA, "2", 0.4, False, ()),
            )
        )


async def test_a_search_result_says_whether_the_name_matched_or_only_looked_alike() -> None:
    nothing = cast(Any, None)
    source = ContractDrugFacts(
        FakeSearch(),
        FakeCatalog(card("1", "Bilaxten", "BILASTINE"), card("2", "Bilazap", "BILASTINE")),
        nothing,
        nothing,
        nothing,
    )

    rows = await source.search_drugs("Bilaxten", 8)

    assert [(r["register_number"], r["name_match"]) for r in rows] == [
        ("1", "exact"),
        ("2", "similar_name_only"),
    ]
