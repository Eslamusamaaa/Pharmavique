"""The person's medicine history as memory (signed in): a new drug against what they take now.

Informational only. A finding is what a source records about two ingredients, with the severity the
source gives; nothing here says to stop, switch or change a dose, and "nothing found" is never
"safe". Only the medicines the person marked as current are compared. The pharmacist or doctor
decides.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pharmavique.bootstrap.api_auth import current_principal
from pharmavique.bootstrap.api_drugs import DISCLAIMER, get_catalog
from pharmavique.bootstrap.api_me import get_watchlist
from pharmavique.bootstrap.history import (
    CurrentInteractions,
    HistoryCheck,
    HistoryFinding,
    current_interactions,
    history_check,
)
from pharmavique.catalog.contracts.queries import CatalogQueries
from pharmavique.interactions.contracts.queries import InteractionChecks
from pharmavique.shared_kernel.principal import Principal
from pharmavique.watchlist.application.service import WatchlistService

router = APIRouter(prefix="/v1/me/history", tags=["history"])

NOTE = (
    "هذه مقارنة بين مكوّنات هذا الدواء وأدويتك الحالية المسجّلة عندنا، من مصادر خارجية، وليست "
    "نصيحة طبية. عدم ظهور تداخل لا يعني أن الجمع آمن، والصيدلي أو الطبيب هو من يقرر. لا تغيّر "
    "دواءً ولا جرعة بناءً على هذه الشاشة."
)
NOTE_EN = (
    "A comparison of this drug's ingredients with the medicines you listed as current, from "
    "outside sources. It is not medical advice. No finding does not mean the combination is "
    "safe. Your pharmacist or doctor decides; do not change a medicine or a dose because of it."
)


def get_checks(request: Request) -> InteractionChecks:
    backend: InteractionChecks | None = request.app.state.interactions
    if backend is None:
        raise HTTPException(status_code=503, detail="interactions are not available")
    return backend


class FindingOut(BaseModel):
    kind: str  # "interaction" or "duplicate_ingredient"
    severity: str | None  # as the source rates it
    source: str | None
    with_register_number: str
    with_name: str  # the medicine you already take
    ingredients: list[str]  # this drug's ingredient, then the other medicine's
    about_register_number: str | None = None  # only in the list among current medicines


class AllergyHitOut(BaseModel):
    allergy: str
    ingredient: str


class MedicineRefOut(BaseModel):
    register_number: str
    name: str


class HistoryCheckOut(BaseModel):
    register_number: str
    name: str
    ingredients: list[str]
    already_taken: bool
    compared_with: list[MedicineRefOut]
    findings: list[FindingOut]
    allergy_matches: list[AllergyHitOut]
    unmatched_ingredients: list[str]  # the source cannot judge these: not "no interaction"
    complete: bool = False  # always: absence of a finding is never a safety verdict
    note: str = NOTE
    note_en: str = NOTE_EN
    disclaimer: str = DISCLAIMER


class CurrentInteractionsOut(BaseModel):
    medicines: list[MedicineRefOut]
    findings: list[FindingOut]
    complete: bool = False
    note: str = NOTE
    note_en: str = NOTE_EN
    disclaimer: str = DISCLAIMER


def _finding(f: HistoryFinding, about: str | None = None) -> FindingOut:
    return FindingOut(
        kind=f.kind,
        severity=f.severity,
        source=f.source,
        with_register_number=f.with_register,
        with_name=f.with_name,
        ingredients=list(f.ingredients),
        about_register_number=about,
    )


def history_out(check: HistoryCheck) -> HistoryCheckOut:
    return HistoryCheckOut(
        register_number=check.register_number,
        name=check.name,
        ingredients=list(check.ingredients),
        already_taken=check.already_taken,
        compared_with=[MedicineRefOut(register_number=r, name=n) for r, n in check.compared_with],
        findings=[_finding(f) for f in check.findings],
        allergy_matches=[
            AllergyHitOut(allergy=a.allergy, ingredient=a.ingredient) for a in check.allergy_matches
        ],
        unmatched_ingredients=list(check.unmatched),
    )


def current_out(result: CurrentInteractions) -> CurrentInteractionsOut:
    return CurrentInteractionsOut(
        medicines=[MedicineRefOut(register_number=r, name=n) for r, n in result.medicines],
        findings=[_finding(f, about) for f, about in result.findings],
    )


Me = Annotated[Principal, Depends(current_principal)]


async def history_for_request(
    request: Request, principal: Principal | None, register_number: str | None
) -> HistoryCheckOut | None:
    """For the assistant when the person asked to use their medicines: the same check as the drug
    page, computed here and never given to a language model."""
    if principal is None:
        raise HTTPException(status_code=401, detail="sign in to use your medicines")
    if not register_number:
        raise HTTPException(status_code=422, detail="name the drug to compare with your medicines")
    watchlist = request.app.state.watchlist
    catalog = request.app.state.catalog
    if watchlist is None or catalog is None:
        raise HTTPException(status_code=503, detail="saved medicines are not configured")
    result = await history_check(
        watchlist, catalog, get_checks(request), principal.user_id, register_number
    )
    return history_out(result) if result is not None else None


@router.get(
    "/check/{register_number}",
    response_model=HistoryCheckOut,
    summary="A drug against the medicines I take now (recorded interactions, my allergies)",
)
async def check_new_drug(
    register_number: str,
    me: Me,
    watchlist: Annotated[WatchlistService, Depends(get_watchlist)],
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    checks: Annotated[InteractionChecks, Depends(get_checks)],
) -> HistoryCheckOut:
    result = await history_check(watchlist, catalog, checks, me.user_id, register_number)
    if result is None:
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    return history_out(result)


@router.get(
    "/interactions",
    response_model=CurrentInteractionsOut,
    summary="Recorded interactions among the medicines I take now",
)
async def among_current(
    me: Me,
    watchlist: Annotated[WatchlistService, Depends(get_watchlist)],
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    checks: Annotated[InteractionChecks, Depends(get_checks)],
) -> CurrentInteractionsOut:
    return current_out(await current_interactions(watchlist, catalog, checks, me.user_id))
