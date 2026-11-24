"""The assistant's search facts: a typed strength matches the registered strength, and a longer
name of the same brand (PLUS, AMLO) is never taken for the product asked about."""

import dataclasses
from collections.abc import Sequence
from typing import Any, cast

from pharmavique.bootstrap.assistant_facts import ContractDrugFacts
from pharmavique.catalog.contracts.queries import IngredientDetail, ProductCard, ProductDetails
from pharmavique.search.contracts.queries import SearchMatch, SearchResult
from pharmavique.shared_kernel.market import Market


def card(number: str, name_en: str, name_ar: str) -> ProductCard:
    return ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=name_en,
        trade_name_ar=name_ar,
        ingredient_names=("BISOPROLOL FUMARATE",),
        dosage_form_en="Film-coated tablet",
        dosage_form_ar=None,
        marketing_company=None,
        manufacturers=(),
        atc_codes=(),
        listing_status="listed",
        authorization_status=None,
        marketing_status=None,
    )


# Real SFDA rows: plain CONCOR has no strength in its name; CONCOR 5 PLUS is another product.
CARDS = {
    "plus": card("plus", "CONCOR 5 PLUS F.C. TABLETS", "كونكور 5 بلوس"),
    "five": card("five", "CONCOR", "كونكور"),
    "ten": card("ten", "CONCOR", "كونكور"),
}
STRENGTH = {"plus": ("5", "12.5"), "five": ("5",), "ten": ("10",)}


class Search:
    async def search(self, query: Any) -> SearchResult:
        return SearchResult(tuple(SearchMatch(Market.SA, n, 0.5, False, ()) for n in CARDS))


class Catalog:
    async def get_cards(
        self, market: Market, register_numbers: Sequence[str]
    ) -> tuple[ProductCard, ...]:
        return tuple(CARDS[n] for n in register_numbers)


class Details:
    async def get_details(self, market: Market, register_number: str) -> ProductDetails:
        lines = tuple(IngredientDetail("BISOPROLOL", s, "mg") for s in STRENGTH[register_number])
        return dataclasses.replace(_template(), card=CARDS[register_number], ingredients=lines)


def _template() -> ProductDetails:
    return ProductDetails(
        card=CARDS["five"],
        ingredients=(),
        route_en=None,
        route_ar=None,
        package_type=None,
        package_size=None,
        legal_status=None,
        distribution_site=None,
        shelf_life=None,
        storage_en=None,
        storage_ar=None,
        marketing_company_country=None,
        manufacturers=(),
        price=None,
        source="sfda",
        source_ref="https://www.sfda.gov.sa/en/x",
        fetched_at=None,
        trust="official",
    )


async def test_a_typed_strength_picks_the_product_with_that_registered_strength() -> None:
    nothing = cast(Any, None)
    facts = ContractDrugFacts(
        Search(), cast(Any, Catalog()), cast(Any, Details()), nothing, nothing
    )

    rows = await facts.search_drugs("كونكور 5", 8)

    assert {r["register_number"]: r["name_match"] for r in rows} == {
        "plus": "longer_name",
        "five": "exact",
        "ten": "similar_name_only",
    }
    assert next(r for r in rows if r["register_number"] == "five")["strengths"] == [
        "BISOPROLOL 5 mg"
    ]
