"""Shortage of a drug as SFDA lists it, with the products that share its ingredients.

Answers from two contexts at once (the catalog's list rows, the substitution verdicts), so it
sits in the composition root next to the other drug endpoints. It reports what SFDA published
and what our rules computed. It never says "switch": the pharmacist or doctor decides.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from pharmavique.bootstrap.api_drugs import (
    DISCLAIMER,
    SameIngredientOut,
    get_details,
    get_equivalence,
    same_ingredient_results,
)
from pharmavique.bootstrap.cached_response import cached_json
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
    # "listed_in_shortage" (the list names this product by generic and trade name), "resolved" or
    # "not_listed". An ingredient-only link is never shown: it would mark every brand as short.
    status: str
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


def _is_current(item: ShortageItemOut) -> bool:
    return item.list_name == CURRENT and item.availability != "resolved"


def _unique(items: list[ShortageItemOut]) -> list[ShortageItemOut]:
    """The list can repeat one row (one per trade name it covers); show it once."""
    seen: set[str] = set()
    kept: list[ShortageItemOut] = []
    for item in items:
        key = item.model_dump_json()
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return kept


def _status(items: list[ShortageItemOut]) -> str:
    current = [i for i in items if _is_current(i)]
    if any(i.confidence == "matched" for i in current):
        return "listed_in_shortage"
    if any(i.confidence == "matched" for i in items):
        return "resolved"
    return "not_listed"


@router.get(
    "/products/{register_number}/shortage",
    response_model=ShortageOut,
    summary="Is this drug on SFDA's shortage list, and which products share its ingredients",
)
async def shortage(
    request: Request,
    register_number: str,
    details_backend: Annotated[CatalogDetails, Depends(get_details)],
    equivalence: Annotated[EquivalenceQueries, Depends(get_equivalence)],
    list_items: Annotated[CatalogListItems, Depends(get_list_items)],
    market: Market = Market.SA,
) -> Response:
    async def compute() -> ShortageOut:
        if await details_backend.get_details(market, register_number) is None:
            raise HTTPException(status_code=404, detail="no such drug in the catalog")
        # Only a row that names this product (generic name AND trade name) counts. A row that names
        # just the ingredient says nothing about which brands are short, and showing it would mark
        # every product with that ingredient as short.
        items = _unique(
            [
                _item(i)
                for i in await list_items.list_items(market, register_number, (CURRENT, RESOLVED))
                if i.confidence == "matched"
            ]
        )
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
                            dict(t.facets).get("availability") != "resolved"
                            and t.confidence == "matched"
                            for t in theirs
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

    return await cached_json(request, "shortage", [register_number, market.value], compute)
