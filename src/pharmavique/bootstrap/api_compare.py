"""Compare two drugs side by side.

The facts come from the catalog; the verdict comes from the `substitution` rules, never from a
model. When the rules cannot be sure it says "possible, needs pharmacist check". Nothing here
recommends choosing one drug over the other.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from pharmavique.bootstrap.api_drugs import (
    DISCLAIMER,
    IngredientOut,
    PriceOut,
    _facts,
    _ingredients,
    _price,
    get_details,
    get_equivalence,
)
from pharmavique.catalog.contracts.queries import CatalogDetails, ProductDetails
from pharmavique.shared_kernel.market import Market
from pharmavique.substitution.contracts.queries import EquivalenceQueries

router = APIRouter(prefix="/v1", tags=["compare"])


class CompareSideOut(BaseModel):
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredients: list[IngredientOut]
    dosage_form_en: str | None
    dosage_form_ar: str | None
    route_en: str | None
    marketing_company: str | None
    manufacturers: list[str]
    legal_status: str | None
    listing_status: str
    authorization_status: str | None
    marketing_status: str | None
    price: PriceOut | None


class CompareOut(BaseModel):
    a: CompareSideOut
    b: CompareSideOut
    verdict: str  # equivalent / possible_needs_pharmacist_check / not_equivalent
    strength: str
    form_family: str
    differences: list[str]  # the fields whose values differ, for the app to highlight
    disclaimer: str = DISCLAIMER


def _side(d: ProductDetails) -> CompareSideOut:
    card = d.card
    return CompareSideOut(
        register_number=card.register_number,
        trade_name_en=card.trade_name_en,
        trade_name_ar=card.trade_name_ar,
        ingredients=_ingredients(d),
        dosage_form_en=card.dosage_form_en,
        dosage_form_ar=card.dosage_form_ar,
        route_en=d.route_en,
        marketing_company=card.marketing_company,
        manufacturers=[m.name for m in d.manufacturers],
        legal_status=d.legal_status,
        listing_status=card.listing_status,
        authorization_status=card.authorization_status,
        marketing_status=card.marketing_status,
        price=_price(d),
    )


def _differences(a: CompareSideOut, b: CompareSideOut) -> list[str]:
    def ingredients(side: CompareSideOut) -> list[tuple[str, str | None, str | None]]:
        return sorted((i.name.upper(), i.strength, i.unit) for i in side.ingredients)

    def price(side: CompareSideOut) -> tuple[str, str | None] | None:
        return (side.price.amount, side.price.currency_code) if side.price else None

    checks = {
        "ingredients": (ingredients(a), ingredients(b)),
        "dosage_form": (a.dosage_form_en, b.dosage_form_en),
        "route": (a.route_en, b.route_en),
        "marketing_company": (a.marketing_company, b.marketing_company),
        "legal_status": (a.legal_status, b.legal_status),
        "listing_status": (a.listing_status, b.listing_status),
        "price": (price(a), price(b)),
    }
    return [name for name, (left, right) in checks.items() if left != right]


@router.get(
    "/compare",
    response_model=CompareOut,
    summary="Two drugs side by side, with the computed equivalence verdict",
)
async def compare(
    a: Annotated[str, Query(min_length=1, max_length=40, description="register number")],
    b: Annotated[str, Query(min_length=1, max_length=40, description="register number")],
    details_backend: Annotated[CatalogDetails, Depends(get_details)],
    equivalence: Annotated[EquivalenceQueries, Depends(get_equivalence)],
    market: Market = Market.SA,
) -> CompareOut:
    if a == b:
        raise HTTPException(status_code=400, detail="choose two different drugs")
    first = await details_backend.get_details(market, a)
    second = await details_backend.get_details(market, b)
    if first is None or second is None:
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    verdict = equivalence.compare(_facts(first), [_facts(second)])[0]
    left, right = _side(first), _side(second)
    return CompareOut(
        a=left,
        b=right,
        verdict=verdict.verdict,
        strength=verdict.strength,
        form_family=verdict.form_family,
        differences=_differences(left, right),
    )
