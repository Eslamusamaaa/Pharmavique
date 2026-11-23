"""Read-only drug endpoints: search by name (typed, misspelled, Arabic or English) and lookup.

This router sits in the composition root because it answers from two contexts at once: `search`
finds the products, the catalog supplies their cards. Both are reached through their published
contracts. Nothing here is medical advice.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from pharmavique.bootstrap.cached_response import cached_json
from pharmavique.catalog.contracts.queries import (
    CatalogDetails,
    CatalogQueries,
    ProductCard,
    ProductDetails,
)
from pharmavique.search.contracts.queries import ProductSearch, SearchQuery
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.text import normalize_text
from pharmavique.substitution.contracts.queries import (
    EquivalenceQueries,
    IngredientFacts,
    ProductFacts,
)

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
    legal_status: str | None = None


class SearchHitOut(ProductOut):
    score: float  # the best similarity any signal found, 0 to 1; the list is ordered by rank
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
        legal_status=card.legal_status,
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
    request: Request,
    q: Annotated[
        str, Query(min_length=1, max_length=200, description="a name or a register number")
    ],
    search_backend: Annotated[ProductSearch, Depends(get_search)],
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    market: Market = Market.SA,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    include_withdrawn: bool = False,
) -> Response:
    async def compute() -> SearchOut:
        return await _search(q, search_backend, catalog, market, limit, include_withdrawn)

    return await cached_json(
        request, "search", [q, market.value, str(limit), str(include_withdrawn)], compute
    )


STRENGTH_BONUS = 0.03  # per number the person wrote that the product's name also carries
MAX_STRENGTH_BONUS = 0.09


def prefer_written_strength(q: str, hits: list["SearchHitOut"]) -> list["SearchHitOut"]:
    """Among results that fit the name about equally, put first the ones whose name carries the
    numbers the person typed ("paracetamol 500" before a 160 mg syrup). A small nudge: a clearly
    better name match still wins, and an exact match (register number) always stays first."""
    wanted = {t for t in normalize_text(q).split() if t.isdigit()}
    if not wanted:
        return hits

    def key(hit: "SearchHitOut") -> tuple[int, float]:
        if hit.exact:
            return (0, 0.0)
        names = f"{hit.trade_name_en or ''} {hit.trade_name_ar or ''}"
        carried = wanted & set(normalize_text(names).split())
        bonus = min(STRENGTH_BONUS * len(carried), MAX_STRENGTH_BONUS)
        return (1, -(hit.score + bonus))

    return sorted(hits, key=key)  # stable: equal keys keep the search order


async def _search(
    q: str,
    search_backend: ProductSearch,
    catalog: CatalogQueries,
    market: Market,
    limit: int,
    include_withdrawn: bool,
) -> SearchOut:
    result = await search_backend.search(SearchQuery(q, market, limit, include_withdrawn))
    cards = await catalog.get_cards(market, [m.register_number for m in result.matches])
    by_number = {card.register_number: card for card in cards}
    hits = [
        SearchHitOut(
            **_product(by_number[m.register_number]).model_dump(),
            score=max(r.score for r in m.reasons),
            exact=m.exact,
            reasons=[ReasonOut(signal=r.signal, rank=r.rank, score=r.score) for r in m.reasons],
        )
        for m in result.matches
        if m.register_number in by_number
    ]
    hits = prefer_written_strength(q, hits)
    return SearchOut(query=q, count=len(hits), results=hits)


@router.get(
    "/products/{register_number}", response_model=ProductOut, summary="One drug by register number"
)
async def product(
    request: Request,
    register_number: str,
    catalog: Annotated[CatalogQueries, Depends(get_catalog)],
    market: Market = Market.SA,
) -> Response:
    async def compute() -> ProductOut:
        cards = await catalog.get_cards(market, [register_number])
        if not cards:
            raise HTTPException(status_code=404, detail="no such drug in the catalog")
        return _product(cards[0])

    return await cached_json(request, "product", [register_number, market.value], compute)


# ---- drug page (B8): full details and same-ingredient products ---------------------------------
class IngredientOut(BaseModel):
    name: str
    strength: str | None
    unit: str | None


class MakerOut(BaseModel):
    name: str
    country: str | None


class PriceOut(BaseModel):
    amount: str
    currency_code: str | None
    currency_basis: str  # always shown: "owner_assumption" means SAR is assumed, not stated


class PriceChangeOut(BaseModel):
    old_price: PriceOut
    new_price: PriceOut
    changed_at: str  # when our snapshots recorded the new price


class ProvenanceOut(BaseModel):
    source: str | None
    source_ref: str | None
    fetched_at: str | None
    trust: str | None


class DrugPageOut(BaseModel):
    market: str
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredients: list[IngredientOut]
    dosage_form_en: str | None
    dosage_form_ar: str | None
    marketing_company: str | None
    listing_status: str
    route_en: str | None
    route_ar: str | None
    package_type: str | None
    package_size: int | None
    legal_status: str | None
    distribution_site: str | None
    shelf_life: str | None
    storage_en: str | None
    storage_ar: str | None
    atc_codes: list[str]
    authorization_status: str | None
    marketing_status: str | None
    marketing_company_country: str | None
    manufacturers: list[MakerOut]
    price: PriceOut | None
    price_change: PriceChangeOut | None = None
    provenance: ProvenanceOut
    disclaimer: str = DISCLAIMER


class SameIngredientOut(BaseModel):
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredients: list[IngredientOut]
    dosage_form_en: str | None
    dosage_form_ar: str | None
    marketing_company: str | None
    price: PriceOut | None
    verdict: str  # computed by substitution: equivalent / possible_needs_pharmacist_check / ...
    strength: str
    form_family: str


class SameIngredientListOut(BaseModel):
    register_number: str
    count: int
    results: list[SameIngredientOut]
    disclaimer: str = DISCLAIMER


def _amount(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if "." not in text or len(text.split(".")[1]) >= 2 else f"{value:.2f}"


def _price(details: ProductDetails) -> PriceOut | None:
    p = details.price
    if p is None:
        return None
    return PriceOut(
        amount=_amount(p.amount), currency_code=p.currency_code, currency_basis=p.currency_basis
    )


def _price_change(details: ProductDetails) -> PriceChangeOut | None:
    change = details.price_change
    if change is None:
        return None
    return PriceChangeOut(
        old_price=PriceOut(
            amount=_amount(change.old.amount),
            currency_code=change.old.currency_code,
            currency_basis=change.old.currency_basis,
        ),
        new_price=PriceOut(
            amount=_amount(change.new.amount),
            currency_code=change.new.currency_code,
            currency_basis=change.new.currency_basis,
        ),
        changed_at=change.changed_at.isoformat(),
    )


def _ingredients(details: ProductDetails) -> list[IngredientOut]:
    return [
        IngredientOut(name=i.name, strength=i.strength, unit=i.unit) for i in details.ingredients
    ]


def _facts(details: ProductDetails) -> ProductFacts:
    return ProductFacts(
        product_id=details.card.register_number,
        ingredients=tuple(IngredientFacts(i.name, i.strength, i.unit) for i in details.ingredients),
        dosage_form=details.card.dosage_form_en,
    )


def get_details(request: Request) -> CatalogDetails:
    backend: CatalogDetails | None = request.app.state.details
    if backend is None:
        raise _unavailable()
    return backend


def get_equivalence(request: Request) -> EquivalenceQueries:
    backend: EquivalenceQueries = request.app.state.equivalence
    return backend


@router.get(
    "/products/{register_number}/details",
    response_model=DrugPageOut,
    summary="The drug page: every registry field with its source and fetch date",
)
async def drug_page(
    request: Request,
    register_number: str,
    details_backend: Annotated[CatalogDetails, Depends(get_details)],
    market: Market = Market.SA,
) -> Response:
    async def compute() -> DrugPageOut:
        return await _drug_page(details_backend, market, register_number)

    return await cached_json(request, "page", [register_number, market.value], compute)


async def _drug_page(
    details_backend: CatalogDetails, market: Market, register_number: str
) -> DrugPageOut:
    found = await details_backend.get_details(market, register_number)
    if found is None:
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    card = found.card
    return DrugPageOut(
        market=card.market.value,
        register_number=card.register_number,
        trade_name_en=card.trade_name_en,
        trade_name_ar=card.trade_name_ar,
        ingredients=_ingredients(found),
        dosage_form_en=card.dosage_form_en,
        dosage_form_ar=card.dosage_form_ar,
        marketing_company=card.marketing_company,
        listing_status=card.listing_status,
        route_en=found.route_en,
        route_ar=found.route_ar,
        package_type=found.package_type,
        package_size=found.package_size,
        legal_status=found.legal_status,
        distribution_site=found.distribution_site,
        shelf_life=found.shelf_life,
        storage_en=found.storage_en,
        storage_ar=found.storage_ar,
        atc_codes=list(card.atc_codes),
        authorization_status=card.authorization_status,
        marketing_status=card.marketing_status,
        marketing_company_country=found.marketing_company_country,
        manufacturers=[MakerOut(name=m.name, country=m.country) for m in found.manufacturers],
        price=_price(found),
        price_change=_price_change(found),
        provenance=ProvenanceOut(
            source=found.source,
            source_ref=found.source_ref,
            fetched_at=found.fetched_at.isoformat() if found.fetched_at else None,
            trust=found.trust,
        ),
    )


async def same_ingredient_results(
    details_backend: CatalogDetails,
    equivalence: EquivalenceQueries,
    market: Market,
    register_number: str,
    limit: int,
) -> list[SameIngredientOut] | None:
    """Products with the same ingredient set, cheapest first, each with its computed verdict.

    None when the base product is not in the catalog. Shared by the same-ingredient and shortage
    endpoints so both say the same thing about the same pair.
    """
    base = await details_backend.get_details(market, register_number)
    if base is None:
        return None
    others = await details_backend.same_ingredients(market, register_number, limit)
    verdicts = {
        c.product_id: c for c in equivalence.compare(_facts(base), [_facts(o) for o in others])
    }
    ordered = sorted(
        others,
        key=lambda o: (
            o.price is None,
            o.price.amount if o.price else Decimal(0),
            o.card.register_number,
        ),
    )
    results = []
    for other in ordered:
        comparison = verdicts[other.card.register_number]
        results.append(
            SameIngredientOut(
                register_number=other.card.register_number,
                trade_name_en=other.card.trade_name_en,
                trade_name_ar=other.card.trade_name_ar,
                ingredients=_ingredients(other),
                dosage_form_en=other.card.dosage_form_en,
                dosage_form_ar=other.card.dosage_form_ar,
                marketing_company=other.card.marketing_company,
                price=_price(other),
                verdict=comparison.verdict,
                strength=comparison.strength,
                form_family=comparison.form_family,
            )
        )
    return results


@router.get(
    "/products/{register_number}/same-ingredient",
    response_model=SameIngredientListOut,
    summary="Products with the same active ingredients, cheapest first, with a computed verdict",
)
async def same_ingredient(
    register_number: str,
    details_backend: Annotated[CatalogDetails, Depends(get_details)],
    equivalence: Annotated[EquivalenceQueries, Depends(get_equivalence)],
    market: Market = Market.SA,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> SameIngredientListOut:
    results = await same_ingredient_results(
        details_backend, equivalence, market, register_number, limit
    )
    if results is None:
        raise HTTPException(status_code=404, detail="no such drug in the catalog")
    return SameIngredientListOut(
        register_number=register_number, count=len(results), results=results
    )
