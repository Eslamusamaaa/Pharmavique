"""Read-only drug endpoints: search by name (typed, misspelled, Arabic or English) and lookup.

This router sits in the composition root because it answers from two contexts at once: `search`
finds the products, the catalog supplies their cards. Both are reached through their published
contracts. Nothing here is medical advice.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from pharmavique.catalog.contracts.queries import CatalogQueries, ProductCard
from pharmavique.search.contracts.queries import ProductSearch, SearchQuery
from pharmavique.shared_kernel.market import Market

DISCLAIMER = (
    "Informational only, not medical advice. The pharmacist or doctor decides. "
    "Source: SFDA registry data; check the SFDA site for the current status."
)

router = APIRouter(prefix="/v1", tags=["drugs"])


class ReasonOut(BaseModel):
    signal: str
    rank: int
    score: float


class ProductOut(BaseModel):
    market: str
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredients: list[str]
    dosage_form_en: str | None
    dosage_form_ar: str | None
    marketing_company: str | None
    listing_status: str


class SearchHitOut(ProductOut):
    score: float
    exact: bool
    reasons: list[ReasonOut]


class SearchOut(BaseModel):
    query: str
    count: int
    results: list[SearchHitOut]
    disclaimer: str = DISCLAIMER


def _product(card: ProductCard) -> ProductOut:
    return ProductOut(
        market=card.market.value,
        register_number=card.register_number,
        trade_name_en=card.trade_name_en,
        trade_name_ar=card.trade_name_ar,
        ingredients=list(card.ingredient_names),
        dosage_form_en=card.dosage_form_en,
        dosage_form_ar=card.dosage_form_ar,
        marketing_company=card.marketing_company,
        listing_status=card.listing_status,
    )


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="the database is not configured: set PHARMAVIQUE_DATABASE_URL and migrate",
    )


def get_search(request: Request) -> ProductSearch:
    backend: ProductSearch | None = request.app.state.search
    if backend is None:
        raise _unavailable()
    return backend


def get_catalog(request: Request) -> CatalogQueries:
    backend: CatalogQueries | None = request.app.state.catalog
    if backend is None:
        raise _unavailable()
    return backend


@router.get("/search", response_model=SearchOut, summary="Find drugs by name or register number")
async def search(
    q: Annotated[
        str, Query(min_length=1, max_length=200, description="a name or a register number")
    ],
    search_backend: Annotated[ProductSearch, Depends(get_search)],
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    market: Market = Market.SA,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    include_withdrawn: bool = False,
) -> SearchOut:
    result = await search_backend.search(SearchQuery(q, market, limit, include_withdrawn))
    cards = await catalog.get_cards(market, [m.register_number for m in result.matches])
    by_number = {card.register_number: card for card in cards}
    hits = [
        SearchHitOut(
            **_product(by_number[m.register_number]).model_dump(),
            score=m.score,
            exact=m.exact,
            reasons=[ReasonOut(signal=r.signal, rank=r.rank, score=r.score) for r in m.reasons],
        )
        for m in result.matches
        if m.register_number in by_number
    ]
    return SearchOut(query=q, count=len(hits), results=hits)


@router.get(
    "/products/{register_number}", response_model=ProductOut, summary="One drug by register number"
)
async def product(
    register_number: str,
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    market: Market = Market.SA,
) -> ProductOut:
    cards = await catalog.get_cards(market, [register_number])
    if not cards:
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    return _product(cards[0])
