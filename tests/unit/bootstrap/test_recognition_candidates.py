"""Scan candidates: among products of one brand the strength and form read decide the order."""

from collections.abc import Sequence
from typing import Any, cast

from pharmavique.bootstrap.recognition_candidates import SearchCandidateFinder
from pharmavique.catalog.contracts.queries import ProductCard
from pharmavique.search.contracts.queries import MatchReason, SearchMatch, SearchResult
from pharmavique.shared_kernel.market import Market

# Real registry names; the search gives every product of the brand the same score.
NAMES = {
    "1": ("AUGMENTIN 228 MG-5ML Powder for oral suspension", "Powder for oral suspension"),
    "2": ("AUGMENTIN TAB 375 MG", "Tablet"),
    "3": ("AUGMENTIN 457MG-5ML SUSPENSION", "Powder for oral suspension"),
    "4": ("AUGMENTIN 625 MG TAB", "Tablet"),
    "5": ("AUGMENTIN 1 G TAB", "Tablet"),
    "6": ("AUGMENTIN 1 G VIAL POWDER FOR IV. INFUSION", "Powder for solution for injection"),
}


def card(number: str) -> ProductCard:
    name, form = NAMES[number]
    return ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=name,
        trade_name_ar=None,
        ingredient_names=("AMOXICILLIN", "CLAVULANIC ACID"),
        dosage_form_en=form,
        dosage_form_ar=None,
        marketing_company=None,
        manufacturers=(),
        atc_codes=(),
        listing_status="listed",
        authorization_status=None,
        marketing_status=None,
    )


class TiedSearch:
    async def search(self, query: Any) -> SearchResult:
        tie = (MatchReason("fuzzy_first", 1, 0.95),)
        matches = tuple(SearchMatch(Market.SA, n, 0.95, False, tie) for n in NAMES)
        return SearchResult(matches[: query.limit])


class Catalog:
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(card(n) for n in register_numbers)


async def test_the_strength_and_form_read_put_that_product_first() -> None:
    finder = SearchCandidateFinder(TiedSearch(), cast(Any, Catalog()))

    one_gram = await finder.find("Augmentin 1 g tablets", 3)
    suspension = await finder.find("Augmentin 457 mg suspension", 3)

    assert one_gram[0].trade_name_en == "AUGMENTIN 1 G TAB"
    assert suspension[0].trade_name_en == "AUGMENTIN 457MG-5ML SUSPENSION"


class ScoredSearch(TiedSearch):
    """The vial scores a little higher on its name, as NEXIUM 40MG VIAL did against the tablet."""

    async def search(self, query: Any) -> SearchResult:
        result = await super().search(query)
        return SearchResult(
            tuple(
                SearchMatch(
                    m.market, m.register_number, 0.97, False, (MatchReason("fuzzy", 1, 0.97),)
                )
                if m.register_number == "6"
                else m
                for m in result.matches
            )
        )


async def test_a_form_read_outweighs_a_slightly_better_name_score() -> None:
    finder = SearchCandidateFinder(ScoredSearch(), cast(Any, Catalog()))

    found = await finder.find("Augmentin 1 g tablets", 3)

    assert found[0].trade_name_en == "AUGMENTIN 1 G TAB"
