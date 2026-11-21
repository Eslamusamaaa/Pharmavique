"""Licensed pharmacies near a person, by city (informational; never about stock).

The SFDA list gives each pharmacy a city and a national-address short code and no coordinates, so
"near" means the cities whose centre is near, nearest first, with their pharmacies. The person's
position is sent in the body of a POST (so it never lands in an access log's URL), is used for the
one computation and is not stored, logged or cached; the answer is `no-store`. Nothing here says a
pharmacy has any drug in stock or is open.
"""

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from pharmavique.bootstrap.api_drugs import DISCLAIMER
from pharmavique.bootstrap.cached_response import cached_json
from pharmavique.bootstrap.pharmacy_finder import CityGroup, Nearby, city_groups, nearby
from pharmavique.catalog.contracts.queries import CatalogPharmacies, CityLocation, Pharmacy
from pharmavique.shared_kernel.geo import valid_coordinates
from pharmavique.shared_kernel.market import Market

router = APIRouter(prefix="/v1/pharmacies", tags=["pharmacies"])

MAX_AGE_SECONDS = 600
MAX_PER_CITY = 50
NOTE = (
    "Licensed pharmacies from the SFDA list, grouped by city. The list gives no street or "
    "coordinates, so distance is to the city centre, not to a pharmacy. A listing does not say a "
    "pharmacy has any drug in stock or is open now: call before you go."
)


class PharmacyOut(BaseModel):
    name: str
    phone: str | None
    address: str  # exactly as SFDA wrote it
    city: str | None
    region: str | None
    short_code: str | None  # the Saudi national address short code
    precision: str = "city"
    source_ref: str
    fetched_at: str | None
    trust: str


class CityOut(BaseModel):
    city_key: str
    city: str
    region: str | None
    pharmacies: int
    located: bool


class CityPharmaciesOut(BaseModel):
    city_key: str
    city: str
    region: str | None
    distance_km: float | None
    shown: int
    total: int
    pharmacies: list[PharmacyOut]


class CitiesOut(BaseModel):
    count: int
    cities: list[CityOut]
    note: str = NOTE


class PharmacyListOut(BaseModel):
    total: int
    count: int
    results: list[PharmacyOut]
    note: str = NOTE


class NearbyIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=40.0, gt=0, le=500)
    per_city: int = Field(default=15, ge=1, le=MAX_PER_CITY)
    market: Market = Market.SA


class NearbyOut(BaseModel):
    radius_km: float
    precision: str = "city"
    cities: list[CityPharmaciesOut]
    nearest_outside: CityPharmaciesOut | None
    pharmacies_without_a_city: int
    pharmacies_in_cities_without_a_point: int
    note: str = NOTE
    disclaimer: str = DISCLAIMER


class Directory:
    """The pharmacies and city points of one market, reloaded every few minutes (385 rows)."""

    def __init__(
        self, pharmacies: tuple[Pharmacy, ...], locations: tuple[CityLocation, ...]
    ) -> None:
        self.pharmacies = pharmacies
        self.locations = locations
        self.groups = city_groups(pharmacies, locations)
        self.loaded_at = time.monotonic()

    def fresh(self) -> bool:
        return time.monotonic() - self.loaded_at < MAX_AGE_SECONDS


_lock = asyncio.Lock()


def get_source(request: Request) -> CatalogPharmacies:
    source: CatalogPharmacies | None = request.app.state.pharmacies
    if source is None:
        raise HTTPException(status_code=503, detail="the database is not configured")
    return source


Source = Annotated[CatalogPharmacies, Depends(get_source)]


async def _directory(request: Request, source: CatalogPharmacies, market: Market) -> Directory:
    cache: dict[str, Directory] = request.app.state.pharmacy_directories
    found = cache.get(market.value)
    if found is not None and found.fresh():
        return found
    async with _lock:
        found = cache.get(market.value)
        if found is None or not found.fresh():
            found = Directory(await source.pharmacies(market), await source.city_locations(market))
            cache[market.value] = found
        return found


def _pharmacy(p: Pharmacy) -> PharmacyOut:
    return PharmacyOut(
        name=p.name,
        phone=p.phone,
        address=p.address,
        city=p.city,
        region=p.region,
        short_code=p.short_code,
        source_ref=p.source_ref,
        fetched_at=p.fetched_at.isoformat() if p.fetched_at else None,
        trust=p.trust,
    )


def _city_out(group: CityGroup, per_city: int) -> CityPharmaciesOut:
    shown = group.pharmacies[:per_city]
    return CityPharmaciesOut(
        city_key=group.city_key,
        city=group.city,
        region=group.region,
        distance_km=group.distance_km,
        shown=len(shown),
        total=len(group.pharmacies),
        pharmacies=[_pharmacy(p) for p in shown],
    )


def _nearby_out(result: Nearby, body: NearbyIn) -> NearbyOut:
    return NearbyOut(
        radius_km=body.radius_km,
        cities=[_city_out(g, body.per_city) for g in result.groups],
        nearest_outside=_city_out(result.nearest_outside, 3) if result.nearest_outside else None,
        pharmacies_without_a_city=result.without_city,
        pharmacies_in_cities_without_a_point=result.without_point,
    )


@router.post(
    "/nearby",
    response_model=NearbyOut,
    summary="Licensed pharmacies by city, nearest city first (position used once, never kept)",
)
async def find_nearby(
    body: NearbyIn, request: Request, response: Response, source: Source
) -> NearbyOut:
    if not valid_coordinates(body.latitude, body.longitude):
        raise HTTPException(status_code=422, detail="the position is not valid")
    directory = await _directory(request, source, body.market)
    result = nearby(
        directory.pharmacies, directory.locations, body.latitude, body.longitude, body.radius_km
    )
    response.headers["Cache-Control"] = "no-store"
    return _nearby_out(result, body)


@router.get("/cities", response_model=CitiesOut, summary="Cities that have licensed pharmacies")
async def cities(request: Request, source: Source, market: Market = Market.SA) -> Response:
    async def compute() -> CitiesOut:
        directory = await _directory(request, source, market)
        return CitiesOut(
            count=len(directory.groups),
            cities=[
                CityOut(
                    city_key=g.city_key,
                    city=g.city,
                    region=g.region,
                    pharmacies=len(g.pharmacies),
                    located=g.latitude is not None,
                )
                for g in directory.groups
            ],
        )

    return await cached_json(request, "pharmacy-cities", [market.value], compute)


@router.get("", response_model=PharmacyListOut, summary="Search licensed pharmacies (no position)")
async def list_pharmacies(
    request: Request,
    source: Source,
    city: Annotated[str | None, Query(max_length=80, description="a city_key")] = None,
    region: Annotated[str | None, Query(max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=80, description="part of a name")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    market: Market = Market.SA,
) -> Response:
    async def compute() -> PharmacyListOut:
        directory = await _directory(request, source, market)
        rows = list(directory.pharmacies)
        if city:
            rows = [p for p in rows if p.city_key == city.casefold()]
        if region:
            rows = [p for p in rows if (p.region or "").casefold() == region.casefold()]
        if q:
            needle = q.casefold().strip()
            rows = [p for p in rows if needle in p.name.casefold()]
        rows.sort(key=lambda p: (p.name.casefold(), p.address))
        page = rows[offset : offset + limit]
        return PharmacyListOut(
            total=len(rows), count=len(page), results=[_pharmacy(p) for p in page]
        )

    return await cached_json(
        request,
        "pharmacy-list",
        [market.value, city or "", region or "", q or "", str(limit), str(offset)],
        compute,
    )
