"""Shortage of a drug as SFDA lists it, with the products that share its ingredients.

Answers from two contexts at once (the catalog's list rows, the substitution verdicts), so it
sits in the composition root next to the other drug endpoints. It reports what SFDA published
and what our rules computed. It never says "switch": the pharmacist or doctor decides.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pharmavique.bootstrap.api_drugs import (
    DISCLAIMER,
    SameIngredientOut,
    get_details,
    get_equivalence,
    same_ingredient_results,
)
from pharmavique.catalog.contracts.queries import CatalogDetails, CatalogListItems, ListItem
from pharmavique.shared_kernel.market import Market
from pharmavique.substitution.contracts.queries import EquivalenceQueries

router = APIRouter(prefix="/v1", tags=["shortage"])

CURRENT = "drug-shortage"
RESOLVED = "drug-shortage-resolved"
MAX_SUBSTITUTES = 10

NOTE_LISTED = (
    "SFDA lists this drug on its shortage list. The products below have the same active "
    "ingredients; whether one can replace it is for your pharmacist or doctor to decide."
)
NOTE_RESOLVED = (
    "SFDA lists a shortage of this drug as resolved. Check the SFDA site for today's status."
)
NOTE_NONE = (
    "No SFDA shortage record is linked to this drug. That does not say it is in stock "
    "at any pharmacy."
)


class ShortageItemOut(BaseModel):
    list_name: str
    availability: str | None  # "unavailable" or "resolved", as the SFDA list says
    confidence: str  # "matched" or "possible" (possible: a person should check the link)
    reason: str
    trade_names: list[str]  # the trade names SFDA's detail page lists for this shortage
    cells: dict[str, str]
    source_ref: str
    fetched_at: str | None
    trust: str


class SubstituteOut(SameIngredientOut):
    also_on_shortage_list: bool


class ShortageOut(BaseModel):
    register_number: str
    status: str  # "listed_in_shortage", "resolved" or "not_listed"
    items: list[ShortageItemOut]
    substitutes: list[SubstituteOut]
    note: str
    disclaimer: str = DISCLAIMER


def get_list_items(request: Request) -> CatalogListItems:
    backend: CatalogListItems | None = request.app.state.list_items
    if backend is None:
        raise HTTPException(
            status_code=503,
            detail="the database is not configured: set PHARMAVIQUE_DATABASE_URL and migrate",
        )
    return backend


def _item(item: ListItem) -> ShortageItemOut:
    facets = dict(item.facets)
    return ShortageItemOut(
        list_name=item.list_name,
        availability=facets.get("availability"),
        confidence=item.confidence,
        reason=item.reason,
        trade_names=sorted({v for k, v in item.detail if k.lower() == "trade name" and v}),
        cells=dict(item.cells),
        source_ref=item.source_ref,
        fetched_at=item.fetched_at.isoformat() if item.fetched_at else None,
        trust=item.trust,
    )


def _status(items: list[ShortageItemOut]) -> str:
    if any(i.list_name == CURRENT and i.availability != "resolved" for i in items):
        return "listed_in_shortage"
    if items:
        return "resolved"
    return "not_listed"


@router.get(
    "/products/{register_number}/shortage",
    response_model=ShortageOut,
    summary="Is this drug on SFDA's shortage list, and which products share its ingredients",
)
async def shortage(
    register_number: str,
    details_backend: Annotated[CatalogDetails, Depends(get_details)],
    equivalence: Annotated[EquivalenceQueries, Depends(get_equivalence)],
    list_items: Annotated[CatalogListItems, Depends(get_list_items)],
    market: Market = Market.SA,
) -> ShortageOut:
    if await details_backend.get_details(market, register_number) is None:
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    items = [
        _item(i) for i in await list_items.list_items(market, register_number, (CURRENT, RESOLVED))
    ]
    status = _status(items)
    substitutes: list[SubstituteOut] = []
    if status == "listed_in_shortage":
        found = await same_ingredient_results(
            details_backend, equivalence, market, register_number, MAX_SUBSTITUTES
        )
        for other in found or []:
            theirs = await list_items.list_items(market, other.register_number, (CURRENT,))
            substitutes.append(
                SubstituteOut(
                    **other.model_dump(),
                    also_on_shortage_list=any(
                        dict(t.facets).get("availability") != "resolved" for t in theirs
                    ),
                )
            )
    note = {
        "listed_in_shortage": NOTE_LISTED,
        "resolved": NOTE_RESOLVED,
        "not_listed": NOTE_NONE,
    }[status]
    return ShortageOut(
        register_number=register_number,
        status=status,
        items=items,
        substitutes=substitutes,
        note=note,
    )
