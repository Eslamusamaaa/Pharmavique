"""The operator's data-quality board: what is missing in the catalog and how the refresh is doing.

Read-only and for the `operator` role only. It counts and reports; it never changes data. A number
that cannot be known (no refresh folder, no log) is reported as unknown, never as zero.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.infrastructure.refresh_files import FileRefreshHistory
from pharmavique.bootstrap.api_auth import require_roles
from pharmavique.catalog.contracts.queries import CatalogQuality
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.principal import Principal, Role

router = APIRouter(prefix="/v1/operator", tags=["operator"])

Operator = Annotated[Principal, Depends(require_roles(Role.OPERATOR))]
REFRESH_DAYS = 7
STALE_AFTER_HOURS = 36  # a daily refresh that has not run in a day and a half is overdue


def get_quality(request: Request) -> CatalogQuality:
    backend: CatalogQuality | None = request.app.state.quality
    if backend is None:
        raise HTTPException(status_code=503, detail="the database is not configured")
    return backend


def get_refresh_history(request: Request) -> FileRefreshHistory | None:
    history: FileRefreshHistory | None = request.app.state.refresh_history
    return history


class ListQualityOut(BaseModel):
    list_name: str
    rows: int
    linked_matched: int
    linked_possible: int
    unlinked: int
    last_fetched_at: datetime | None


class CatalogOut(BaseModel):
    products: int
    listed: int
    withdrawn: int
    listed_without_price: int
    listed_without_ingredients: int
    listed_with_missing_strength: int
    listed_without_manufacturer: int
    listed_with_real_picture: int
    listed_with_generated_picture: int
    listed_without_picture: int
    lists: list[ListQualityOut]


class StepOut(BaseModel):
    name: str
    exit_code: int
    minutes: float
    failed: bool


class LoadOut(BaseModel):
    loaded: int | None
    skipped: int | None
    rejected: int | None


class RefreshDayOut(BaseModel):
    day: date
    steps: list[StepOut]
    failed_steps: list[str]
    load: LoadOut | None


class RefreshOut(BaseModel):
    available: bool  # false when this server has no refresh folder to read
    last_day: date | None
    days_since_last: int | None
    overdue: bool | None
    days: list[RefreshDayOut]


class ProjectionOut(BaseModel):
    products: int
    built_at: datetime | None
    first_built_at: datetime | None
    events_7d: int


class QualityOut(BaseModel):
    market: str
    generated_at: datetime
    catalog: CatalogOut
    refresh: RefreshOut
    analytics: ProjectionOut | None
    notes: list[str]


def _refresh(history: FileRefreshHistory | None, now: datetime) -> RefreshOut:
    days = history.recent(REFRESH_DAYS) if history is not None else []
    if not days:
        return RefreshOut(
            available=False, last_day=None, days_since_last=None, overdue=None, days=[]
        )
    last = days[0].day
    since = (now.date() - last).days
    return RefreshOut(
        available=True,
        last_day=last,
        days_since_last=since,
        overdue=since * 24 > STALE_AFTER_HOURS,
        days=[
            RefreshDayOut(
                day=d.day,
                steps=[
                    StepOut(name=s.name, exit_code=s.exit_code, minutes=s.minutes, failed=s.failed)
                    for s in d.steps
                ],
                failed_steps=list(d.failed_steps),
                load=LoadOut(loaded=d.load.loaded, skipped=d.load.skipped, rejected=d.load.rejected)
                if d.load
                else None,
            )
            for d in days
        ],
    )


@router.get("/quality", response_model=QualityOut, summary="What is missing and how the refresh is")
async def quality(
    request: Request,
    _: Operator,
    catalog: Annotated[CatalogQuality, Depends(get_quality)],
    history: Annotated[FileRefreshHistory | None, Depends(get_refresh_history)],
    market: Market = Market.SA,
) -> QualityOut:
    now = datetime.now(UTC)
    stats = await catalog.quality_stats(market)
    service: AnalyticsService | None = request.app.state.analytics
    status = await service.status(market) if service is not None else None
    notes = [
        "Counts are of listed products unless a row says otherwise.",
        "A list row without a link is normal for lists that are not about drugs.",
        "Rejected and skipped counts come from the last drug load log; they are unknown "
        "when no log exists.",
    ]
    return QualityOut(
        market=market.value,
        generated_at=now,
        catalog=CatalogOut(
            products=stats.products,
            listed=stats.listed,
            withdrawn=stats.withdrawn,
            listed_without_price=stats.listed_without_price,
            listed_without_ingredients=stats.listed_without_ingredients,
            listed_with_missing_strength=stats.listed_with_missing_strength,
            listed_without_manufacturer=stats.listed_without_manufacturer,
            listed_with_real_picture=stats.listed_with_real_picture,
            listed_with_generated_picture=stats.listed_with_generated_picture,
            listed_without_picture=stats.listed_without_picture,
            lists=[
                ListQualityOut(
                    list_name=x.list_name,
                    rows=x.rows,
                    linked_matched=x.linked_matched,
                    linked_possible=x.linked_possible,
                    unlinked=x.unlinked,
                    last_fetched_at=x.last_fetched_at,
                )
                for x in stats.lists
            ],
        ),
        refresh=_refresh(history, now),
        analytics=ProjectionOut(
            products=status.products,
            built_at=status.built_at,
            first_built_at=status.first_built_at,
            events_7d=status.events_7d,
        )
        if status is not None
        else None,
        notes=notes,
    )
