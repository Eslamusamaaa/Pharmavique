"""Company views: the market map of an ingredient, thin strengths and forms, and the radar.

For the `company` role (and the operator). Everything is computed from official registry rows. There
are no sales, stock or demand figures here, so a thin cell is "few registered makers", never
"unmet demand". Prices are registered prices per pack as the source states them.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.domain.market import THIN_AT, Gaps, MarketMap
from pharmavique.analytics.domain.radar import RadarItem
from pharmavique.bootstrap.api_auth import require_roles
from pharmavique.bootstrap.api_drugs import DISCLAIMER
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.principal import Principal, Role

router = APIRouter(prefix="/v1/company", tags=["company"])

NOTE = (
    "Counts come from the official registry (SFDA) rows as of the last rebuild. They are not "
    "sales, stock or demand figures. Prices are registered prices per pack; packs differ."
)
GAP_NOTE = (
    "A thin cell has few registered makers. A missing cell is a strength and a form that both "
    "exist for this ingredient but never together; it may not make sense clinically or legally. "
    "Neither says anything about demand."
)

Caller = Annotated[Principal, Depends(require_roles(Role.COMPANY, Role.OPERATOR))]


def get_analytics(request: Request) -> AnalyticsService:
    service: AnalyticsService | None = request.app.state.analytics
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="company views are not configured: set PHARMAVIQUE_DATABASE_URL, migrate, "
            "and run `pharmavique analytics-rebuild`",
        )
    return service


Analytics = Annotated[AnalyticsService, Depends(get_analytics)]


class PriceRangeOut(BaseModel):
    currency_code: str | None
    currency_basis: str  # "source_stated", "owner_assumption" or "unconfirmed"; always shown
    count: int
    lowest: Decimal
    highest: Decimal


class CountOut(BaseModel):
    name: str
    count: int


class GroupOut(BaseModel):
    ingredients: list[str]
    listed: int
    withdrawn: int
    makers: int
    forms: list[CountOut]
    strengths: list[CountOut]
    price_ranges: list[PriceRangeOut]


class MarketMapOut(BaseModel):
    ingredient: str
    listed: int
    withdrawn: int
    makers: int
    top_makers: list[CountOut]
    groups: list[GroupOut]
    note: str = NOTE
    disclaimer: str = DISCLAIMER


class GapCellOut(BaseModel):
    ingredients: list[str]
    strength: str
    dosage_form: str
    products: int
    makers: int
    thin: bool


class MissingCellOut(BaseModel):
    ingredients: list[str]
    strength: str
    dosage_form: str


class GapsOut(BaseModel):
    ingredient: str
    thin_at: int
    cells: list[GapCellOut]
    missing: list[MissingCellOut]
    note: str = GAP_NOTE
    disclaimer: str = DISCLAIMER


class RadarItemOut(BaseModel):
    kind: str  # added, relisted, withdrawn, price_changed
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    marketing_company: str | None
    ingredients: list[str]
    occurred_at: datetime
    old_price: str | None
    new_price: str | None
    currency_code: str | None
    currency_basis: str | None


class RadarOut(BaseModel):
    ingredient: str | None
    days: int
    count: int
    items: list[RadarItemOut]
    note: str = (
        "Changes seen in the registry since the radar started counting (the first rebuild). "
        "It shows what changed, not why."
    )
    disclaimer: str = DISCLAIMER


def _pairs(rows: tuple[tuple[str, int], ...]) -> list[CountOut]:
    return [CountOut(name=name, count=count) for name, count in rows]


def _map_out(result: MarketMap) -> MarketMapOut:
    return MarketMapOut(
        ingredient=result.ingredient,
        listed=result.listed,
        withdrawn=result.withdrawn,
        makers=result.makers,
        top_makers=_pairs(result.top_makers),
        groups=[
            GroupOut(
                ingredients=list(g.ingredients),
                listed=g.listed,
                withdrawn=g.withdrawn,
                makers=g.makers,
                forms=_pairs(g.forms),
                strengths=_pairs(g.strengths),
                price_ranges=[
                    PriceRangeOut(
                        currency_code=r.currency_code,
                        currency_basis=r.currency_basis,
                        count=r.count,
                        lowest=r.lowest,
                        highest=r.highest,
                    )
                    for r in g.price_ranges
                ],
            )
            for g in result.groups
        ],
    )


def _gaps_out(result: Gaps) -> GapsOut:
    return GapsOut(
        ingredient=result.ingredient,
        thin_at=result.thin_at,
        cells=[
            GapCellOut(
                ingredients=list(c.ingredients),
                strength=c.strength_key,
                dosage_form=c.dosage_form,
                products=c.products,
                makers=c.makers,
                thin=c.thin,
            )
            for c in result.cells
        ],
        missing=[
            MissingCellOut(
                ingredients=list(m.ingredients), strength=m.strength_key, dosage_form=m.dosage_form
            )
            for m in result.missing
        ],
    )


def _radar_out(item: RadarItem) -> RadarItemOut:
    event = item.event
    return RadarItemOut(
        kind=event.kind.value,
        register_number=event.register_number,
        trade_name_en=item.trade_name_en,
        trade_name_ar=item.trade_name_ar,
        marketing_company=item.marketing_company,
        ingredients=list(item.ingredients),
        occurred_at=event.occurred_at,
        old_price=event.old_price,
        new_price=event.new_price,
        currency_code=event.currency_code,
        currency_basis=event.currency_basis,
    )


@router.get("/market", response_model=MarketMapOut, summary="Who sells an ingredient, and how")
async def market_map(
    _: Caller,
    service: Analytics,
    ingredient: Annotated[str, Query(min_length=2, max_length=120)],
    market: Market = Market.SA,
) -> MarketMapOut:
    try:
        return _map_out(await service.market_map(market, ingredient))
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("/gaps", response_model=GapsOut, summary="Thin and missing strengths and forms")
async def gaps(
    _: Caller,
    service: Analytics,
    ingredient: Annotated[str, Query(min_length=2, max_length=120)],
    thin_at: Annotated[int, Query(ge=0, le=20)] = THIN_AT,
    market: Market = Market.SA,
) -> GapsOut:
    try:
        return _gaps_out(await service.gaps(market, ingredient, thin_at))
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("/radar", response_model=RadarOut, summary="What changed in the registry lately")
async def radar(
    _: Caller,
    service: Analytics,
    ingredient: Annotated[str | None, Query(min_length=2, max_length=120)] = None,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    market: Market = Market.SA,
) -> RadarOut:
    try:
        found = await service.radar(market, ingredient, days, limit)
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return RadarOut(
        ingredient=ingredient.upper() if ingredient else None,
        days=days,
        count=len(found),
        items=[_radar_out(item) for item in found],
    )
