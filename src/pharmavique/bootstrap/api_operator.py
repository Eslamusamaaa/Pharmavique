"""The operator's views: the data-quality board and the pharmacist and company accounts to verify.

For the `operator` role only. The quality board counts and reports; it never changes data, and a
number that cannot be known (no refresh folder, no log) is reported as unknown, never as zero. The
account review verifies or rejects a professional role and emails the person (ADR-020).
"""

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.infrastructure.refresh_files import FileRefreshHistory
from pharmavique.bootstrap.api_auth import (
    UserOut,
    deliver,
    get_email_sender,
    get_identity,
    require_roles,
    user_out,
)
from pharmavique.catalog.contracts.queries import CatalogQuality
from pharmavique.identity.application.service import IdentityService
from pharmavique.identity.domain.user import MAX_REVIEW_NOTE_LENGTH, AccountNotFound, RoleReview
from pharmavique.shared_kernel.email import EmailSender
from pharmavique.shared_kernel.errors import InvariantViolation
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


class PendingAccountOut(BaseModel):
    id: UUID
    email: str
    role: str
    created_at: datetime | None
    role_review: RoleReview


class PendingAccountsOut(BaseModel):
    count: int
    accounts: list[PendingAccountOut]


class ReviewIn(BaseModel):
    decision: Literal["verified", "rejected"]
    note: str | None = Field(default=None, max_length=MAX_REVIEW_NOTE_LENGTH)


Identity = Annotated[IdentityService, Depends(get_identity)]


@router.get(
    "/accounts/pending",
    response_model=PendingAccountsOut,
    summary="Pharmacist and company accounts waiting to be verified, oldest first",
)
async def pending_accounts(_: Operator, identity: Identity) -> PendingAccountsOut:
    views = await identity.pending_role_reviews()
    return PendingAccountsOut(
        count=len(views),
        accounts=[
            PendingAccountOut(
                id=v.id,
                email=v.email,
                role=v.role.value,
                created_at=v.created_at,
                role_review=v.role_review,
            )
            for v in views
        ],
    )


@router.post(
    "/accounts/{user_id}/review",
    response_model=UserOut,
    summary="Verify or reject a pharmacist or company account; the person is emailed",
)
async def review_account(
    _: Operator,
    user_id: UUID,
    body: ReviewIn,
    identity: Identity,
    sender: Annotated[EmailSender | None, Depends(get_email_sender)],
) -> UserOut:
    try:
        view, message = await identity.review_role(
            user_id, approve=body.decision == "verified", note=body.note
        )
    except AccountNotFound:
        raise HTTPException(status_code=404, detail="no such account") from None
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    await deliver(sender, message)
    return user_out(view)
