"""The signed-in person's saved medicines, allergies, alerts and weekly digest.

Everything here belongs to the caller: the token says who they are, and the database also limits
every query to their rows. Allergy checks are by active-ingredient name only and say so; they never
say a medicine is safe, and never tell anyone to stop or switch.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from pharmavique.bootstrap.api_auth import current_principal
from pharmavique.bootstrap.api_drugs import DISCLAIMER, ProductOut, _product, get_catalog
from pharmavique.catalog.contracts.queries import CatalogIngredients, CatalogQueries
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.principal import Principal
from pharmavique.watchlist.application.service import WatchlistService
from pharmavique.watchlist.domain.model import Alert, AlertKind, MedicineStatus

router = APIRouter(prefix="/v1", tags=["me"])

ALLERGY_NOTE = (
    "Matched by active ingredient name only. A class allergy (for example penicillin and "
    "amoxicillin) is not covered, and no match is not a clearance. Ask your pharmacist."
)
DIGEST_KINDS = {
    AlertKind.PRICE_CHANGED: "تغيير سعر",
    AlertKind.WITHDRAWN: "سحب من السجل",
    AlertKind.RELISTED: "رجوع للسجل",
}


def get_watchlist(request: Request) -> WatchlistService:
    service: WatchlistService | None = request.app.state.watchlist
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="saved medicines are not configured: set PHARMAVIQUE_DATABASE_URL, migrate",
        )
    return service


def get_ingredients(request: Request) -> CatalogIngredients:
    backend: CatalogIngredients | None = request.app.state.ingredients
    if backend is None:
        raise HTTPException(status_code=503, detail="the database is not configured")
    return backend


Me = Annotated[Principal, Depends(current_principal)]
Watchlist = Annotated[WatchlistService, Depends(get_watchlist)]


class AllergyMatchOut(BaseModel):
    allergy: str
    ingredient: str


class SavedMedicineOut(BaseModel):
    register_number: str
    added_at: str
    status: str  # "current" (taken now) or "past" (taken before): the person's own record
    status_changed_at: str | None
    product: ProductOut | None  # None when the registry no longer has it
    allergy_matches: list[AllergyMatchOut]


class SavedMedicinesOut(BaseModel):
    count: int
    items: list[SavedMedicineOut]
    allergy_note: str = ALLERGY_NOTE
    disclaimer: str = DISCLAIMER


class AllergyIn(BaseModel):
    ingredient: str = Field(min_length=1, max_length=200)


class AllergyOut(BaseModel):
    ingredient: str


class AllergiesOut(BaseModel):
    items: list[AllergyOut]
    note: str = ALLERGY_NOTE


class AllergyCheckOut(BaseModel):
    register_number: str
    matches: list[AllergyMatchOut]
    checked_allergies: int
    note: str = ALLERGY_NOTE


class AlertOut(BaseModel):
    id: UUID
    kind: str
    register_number: str
    product: ProductOut | None
    occurred_at: str
    details: dict[str, str | None]
    read: bool


class AlertsOut(BaseModel):
    unread: int
    items: list[AlertOut]


class MarkReadIn(BaseModel):
    alert_id: UUID | None = None  # none: mark every alert read


async def _cards(catalog: CatalogQueries, numbers: list[str]) -> dict[str, ProductOut]:
    found = await catalog.get_cards(Market.SA, numbers) if numbers else ()
    return {c.register_number: _product(c) for c in found}


def _alert_out(alert: Alert, products: dict[str, ProductOut]) -> AlertOut:
    return AlertOut(
        id=alert.id,
        kind=alert.kind.value,
        register_number=alert.register_number,
        product=products.get(alert.register_number),
        occurred_at=alert.occurred_at.isoformat(),
        details=dict(alert.details),
        read=alert.read_at is not None,
    )


# ---- saved medicines --------------------------------------------------------------------------
@router.get("/me/medicines", response_model=SavedMedicinesOut, summary="My saved medicines")
async def my_medicines(
    me: Me, watchlist: Watchlist, catalog: Annotated[CatalogQueries, Depends(get_catalog)]
) -> SavedMedicinesOut:
    saved = await watchlist.medicines(me.user_id)
    products = await _cards(catalog, [m.register_number for m in saved])
    items = []
    for medicine in saved:
        product = products.get(medicine.register_number)
        matches = (
            await watchlist.check_allergies(me.user_id, product.ingredients) if product else []
        )
        items.append(
            SavedMedicineOut(
                register_number=medicine.register_number,
                added_at=medicine.added_at.isoformat(),
                status=medicine.status.value,
                status_changed_at=(
                    medicine.status_changed_at.isoformat() if medicine.status_changed_at else None
                ),
                product=product,
                allergy_matches=[
                    AllergyMatchOut(allergy=m.allergy, ingredient=m.ingredient) for m in matches
                ],
            )
        )
    return SavedMedicinesOut(count=len(items), items=items)


@router.put("/me/medicines/{register_number}", status_code=204, summary="Save a medicine")
async def save_medicine(
    register_number: str,
    me: Me,
    watchlist: Watchlist,
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
) -> Response:
    if not await catalog.get_cards(Market.SA, [register_number]):
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    try:
        await watchlist.save_medicine(me.user_id, register_number)
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return Response(status_code=204)


class StatusIn(BaseModel):
    status: MedicineStatus


@router.put(
    "/me/medicines/{register_number}/status",
    status_code=204,
    summary="Mark a saved medicine as one I take now, or took before",
)
async def set_medicine_status(
    register_number: str, body: StatusIn, me: Me, watchlist: Watchlist
) -> Response:
    if not await watchlist.set_status(me.user_id, register_number, body.status):
        raise HTTPException(status_code=404, detail="this medicine is not in your list")
    return Response(status_code=204)


@router.delete("/me/medicines/{register_number}", status_code=204, summary="Remove a medicine")
async def remove_medicine(register_number: str, me: Me, watchlist: Watchlist) -> Response:
    await watchlist.remove_medicine(me.user_id, register_number)
    return Response(status_code=204)


# ---- allergies --------------------------------------------------------------------------------
@router.get("/ingredients", summary="Active ingredient names that start with the text")
async def ingredients(
    q: Annotated[str, Query(min_length=2, max_length=60)],
    backend: Annotated[CatalogIngredients, Depends(get_ingredients)],
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> dict[str, list[str]]:
    return {"items": list(await backend.find_ingredients(Market.SA, q, limit))}


@router.get("/me/allergies", response_model=AllergiesOut, summary="My recorded allergies")
async def my_allergies(me: Me, watchlist: Watchlist) -> AllergiesOut:
    return AllergiesOut(
        items=[AllergyOut(ingredient=a.ingredient) for a in await watchlist.allergies(me.user_id)]
    )


@router.put("/me/allergies", status_code=204, summary="Record an allergy to an active ingredient")
async def add_allergy(
    body: AllergyIn,
    me: Me,
    watchlist: Watchlist,
    backend: Annotated[CatalogIngredients, Depends(get_ingredients)],
) -> Response:
    if not await backend.is_ingredient(Market.SA, body.ingredient):
        raise HTTPException(
            status_code=422, detail="pick an active ingredient from the catalog's list"
        )
    try:
        await watchlist.add_allergy(me.user_id, body.ingredient.upper())
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return Response(status_code=204)


@router.delete("/me/allergies", status_code=204, summary="Remove a recorded allergy")
async def remove_allergy(
    ingredient: Annotated[str, Query(min_length=1, max_length=200)], me: Me, watchlist: Watchlist
) -> Response:
    try:
        await watchlist.remove_allergy(me.user_id, ingredient)
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return Response(status_code=204)


@router.get(
    "/me/allergy-check/{register_number}",
    response_model=AllergyCheckOut,
    summary="Does this medicine contain an ingredient I recorded an allergy to (by name)",
)
async def allergy_check(
    register_number: str,
    me: Me,
    watchlist: Watchlist,
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
) -> AllergyCheckOut:
    cards = await catalog.get_cards(Market.SA, [register_number])
    if not cards:
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    mine = await watchlist.allergies(me.user_id)
    matches = await watchlist.check_allergies(me.user_id, cards[0].ingredient_names)
    return AllergyCheckOut(
        register_number=register_number,
        matches=[AllergyMatchOut(allergy=m.allergy, ingredient=m.ingredient) for m in matches],
        checked_allergies=len(mine),
    )


# ---- alerts and digest -------------------------------------------------------------------------
@router.get("/me/alerts", response_model=AlertsOut, summary="Alerts about my saved medicines")
async def my_alerts(
    me: Me,
    watchlist: Watchlist,
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AlertsOut:
    alerts = await watchlist.alerts(me.user_id, unread_only, limit)
    products = await _cards(catalog, sorted({a.register_number for a in alerts}))
    return AlertsOut(
        unread=await watchlist.unread_count(me.user_id),
        items=[_alert_out(a, products) for a in alerts],
    )


@router.post("/me/alerts/read", summary="Mark one alert, or all of them, as read")
async def mark_alerts_read(body: MarkReadIn, me: Me, watchlist: Watchlist) -> dict[str, int]:
    return {"marked": await watchlist.mark_read(me.user_id, body.alert_id)}


class DigestOut(BaseModel):
    days: int
    since: str
    counts: dict[str, int]
    summary: str  # built only from the counts, never from a model
    items: list[AlertOut]
    disclaimer: str = DISCLAIMER


@router.get(
    "/me/digest",
    response_model=DigestOut,
    summary="What changed for my saved medicines in the last days",
)
async def digest(
    me: Me,
    watchlist: Watchlist,
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    days: Annotated[int, Query(ge=1, le=31)] = 7,
) -> DigestOut:
    since = datetime.now(UTC) - timedelta(days=days)
    recent = [a for a in await watchlist.alerts(me.user_id, False, 100) if a.occurred_at >= since]
    products = await _cards(catalog, sorted({a.register_number for a in recent}))
    counts = Counter(a.kind for a in recent)
    parts = [f"{counts[k]} {label}" for k, label in DIGEST_KINDS.items() if counts[k]]
    summary = (
        f"خلال آخر {days} أيام: " + "، ".join(parts)
        if parts
        else f"ما فيه تغييرات مسجلة في أدويتك خلال آخر {days} أيام"
    )
    return DigestOut(
        days=days,
        since=since.isoformat(),
        counts={k.value: counts[k] for k in DIGEST_KINDS},
        summary=summary,
        items=[_alert_out(a, products) for a in recent],
    )
