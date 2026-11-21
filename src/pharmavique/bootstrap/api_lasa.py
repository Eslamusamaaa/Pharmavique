"""Look-alike sound-alike (LASA) names for a drug, shown on the drug page.

It tells the reader that a differently named drug is spelled or sounds alike, so a label or a
handwritten line deserves a second look. It says nothing about the drugs themselves, whether they
treat the same thing, or which one to use. The name index is built from the catalog on first use.
"""

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from pharmavique.bootstrap.api_drugs import DISCLAIMER, get_catalog
from pharmavique.catalog.contracts.queries import CatalogQueries, ProductCard
from pharmavique.search.domain.lasa import LasaIndex, LasaMatch
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.names import core_name

router = APIRouter(prefix="/v1", tags=["lasa"])

PAGE = 5000
WINDOW = 30  # how many look-alikes are ranked before the weaker ones are set aside
MAX_AGE_SECONDS = 24 * 3600
NOTE = (
    "These names are spelled or sound like this one. Double-check the name on a label or a "
    "prescription. The list is computed from names only and has not been reviewed by a pharmacist."
)


class LasaState:
    """The English and Arabic name indexes of one market, rebuilt once a day."""

    def __init__(self, english: LasaIndex, arabic: LasaIndex) -> None:
        self.english = english
        self.arabic = arabic
        self.built_at = time.monotonic()

    def fresh(self) -> bool:
        return time.monotonic() - self.built_at < MAX_AGE_SECONDS


async def build_state(catalog: CatalogQueries, market: Market) -> LasaState:
    english: list[tuple[str, str]] = []
    arabic: list[tuple[str, str]] = []
    after: str | None = None
    while True:
        page = await catalog.export_cards(market, after, PAGE)
        for card in page.cards:
            if card.trade_name_en:
                english.append((card.register_number, core_name(card.trade_name_en)))
            if card.trade_name_ar:
                arabic.append((card.register_number, core_name(card.trade_name_ar)))
        if page.next_after is None:
            break
        after = page.next_after
    return LasaState(LasaIndex(english), LasaIndex(arabic))


class SimilarNameOut(BaseModel):
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    level: str  # "high" or "medium"
    reasons: list[str]  # "sounds_alike", "spelled_alike"
    scripts: list[str]  # "en" and/or "ar": which spelling matched
    same_ingredients: bool
    ingredients: list[str]


class SimilarNamesOut(BaseModel):
    register_number: str
    count: int
    results: list[SimilarNameOut]
    reviewed: bool = False
    shown_level: str = "high"  # "high", or "all" when the weaker matches were asked for
    hidden_weaker: int = 0  # weaker matches (only spelled alike) that are not shown
    note: str = NOTE
    disclaimer: str = DISCLAIMER


_lock = asyncio.Lock()


async def _state(request: Request, catalog: CatalogQueries, market: Market) -> LasaState:
    state: LasaState | None = request.app.state.lasa
    if state is not None and state.fresh():
        return state
    async with _lock:
        state = request.app.state.lasa
        if state is None or not state.fresh():
            state = await build_state(catalog, market)
            request.app.state.lasa = state
        return state


def _merge(
    found: list[tuple[str, LasaMatch]],
) -> dict[str, tuple[LasaMatch, list[str], set[str]]]:
    merged: dict[str, tuple[LasaMatch, list[str], set[str]]] = {}
    for script, match in found:
        if match.register_number not in merged:
            merged[match.register_number] = (match, [script], set(match.reasons))
            continue
        best, scripts, reasons = merged[match.register_number]
        reasons |= set(match.reasons)
        scripts.append(script)
        merged[match.register_number] = (
            match if match.score > best.score else best,
            scripts,
            reasons,
        )
    return merged


def _out(
    card: ProductCard, base: ProductCard, match: LasaMatch, scripts: list[str], reasons: set[str]
) -> SimilarNameOut:
    return SimilarNameOut(
        register_number=card.register_number,
        trade_name_en=card.trade_name_en,
        trade_name_ar=card.trade_name_ar,
        level=match.level,
        reasons=sorted(reasons),
        scripts=sorted(scripts),
        same_ingredients=set(card.ingredient_names) == set(base.ingredient_names),
        ingredients=list(card.ingredient_names),
    )


@router.get(
    "/products/{register_number}/similar-names",
    response_model=SimilarNamesOut,
    summary="Drugs whose names are spelled or sound like this one (informational)",
)
async def similar_names(
    request: Request,
    register_number: str,
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    market: Market = Market.SA,
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
    include_weaker: Annotated[
        bool, Query(description="also list matches that are only spelled alike")
    ] = False,
) -> SimilarNamesOut:
    cards = await catalog.get_cards(market, [register_number])
    if not cards:
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    base = cards[0]
    state = await _state(request, catalog, market)
    found = [("en", m) for m in state.english.similar_to(register_number, WINDOW)] + [
        ("ar", m) for m in state.arabic.similar_to(register_number, WINDOW)
    ]
    merged = _merge(found)
    ranked_all = sorted(merged.items(), key=lambda kv: (-kv[1][0].score, kv[0]))
    # On the real catalog about a quarter of the names had some match, which is too many to be
    # useful: only the strong ones (they sound alike, or are very close in spelling) show by
    # default.
    strong = [kv for kv in ranked_all if kv[1][0].level == "high"]
    ranked = (ranked_all if include_weaker else strong)[:limit]
    hidden = 0 if include_weaker else len(ranked_all) - len(strong)
    others = {c.register_number: c for c in await catalog.get_cards(market, [n for n, _ in ranked])}
    results = [
        _out(others[number], base, match, scripts, reasons)
        for number, (match, scripts, reasons) in ranked
        if number in others
    ]
    return SimilarNamesOut(
        register_number=register_number,
        count=len(results),
        results=results,
        shown_level="all" if include_weaker else "high",
        hidden_weaker=hidden,
    )
