"""The assistant's same-ingredient facts keep the equivalents, however many products share them."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from pharmavique.bootstrap.assistant_facts import ContractDrugFacts
from pharmavique.catalog.contracts.queries import (
    IngredientDetail,
    PriceDetail,
    ProductCard,
    ProductDetails,
)
from pharmavique.shared_kernel.market import Market
from pharmavique.substitution.application.compare import CompareProductsHandler


def details(number: str, strength: str, form: str, price: str) -> ProductDetails:
    card = ProductCard(
        market=Market.SA,
        register_number=number,
        trade_name_en=f"DRUG {number}",
        trade_name_ar=None,
        ingredient_names=("AMOXICILLIN",),
        dosage_form_en=form,
        dosage_form_ar=None,
        marketing_company=None,
        manufacturers=(),
        atc_codes=(),
        listing_status="listed",
        authorization_status=None,
        marketing_status=None,
    )
    return ProductDetails(
        card=card,
        ingredients=(IngredientDetail("AMOXICILLIN", strength, "mg"),),
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
        price=PriceDetail(Decimal(price), "SAR", "owner_assumption"),
        source="sfda-drugs-list-web",
        source_ref="https://www.sfda.gov.sa/en/x",
        fetched_at=datetime(2026, 11, 17, tzinfo=UTC),
        trust="official",
    )


PRODUCTS = {"1": details("1", "875", "Tablet", "78")}
for n in range(10, 40):
    PRODUCTS[str(n)] = details(str(n), "125", "Oral suspension", f"{n / 10:.2f}")
PRODUCTS["90"] = details("90", "875", "Tablet", "60")


class CheapestFirst:
    """Like the database: products with the ingredient set, cheapest first, cut at `limit`."""

    async def get_details(self, market: Market, register_number: str) -> ProductDetails | None:
        return PRODUCTS.get(register_number)

    async def same_ingredients(
        self, market: Market, register_number: str, limit: int
    ) -> tuple[ProductDetails, ...]:
        ordered = sorted(
            (p for n, p in PRODUCTS.items() if n != register_number),
            key=lambda p: p.price.amount if p.price else Decimal(0),
        )
        return tuple(ordered)[:limit]


async def test_the_equivalent_is_returned_even_when_cheaper_forms_fill_the_limit() -> None:
    nothing = cast(Any, None)
    facts = ContractDrugFacts(nothing, nothing, CheapestFirst(), CompareProductsHandler(), nothing)

    rows = await facts.same_ingredient("1", 15)

    assert len(rows) == 15
    assert rows[0]["register_number"] == "90"
    assert rows[0]["verdict"] == "equivalent"
