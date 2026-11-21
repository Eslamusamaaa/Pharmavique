"""`pharmavique geocode-cities`: find one point for each city that has licensed pharmacies.

Run once (and again when a new city appears in the pharmacy list): it looks up only the cities that
have no point yet, one request a second, with a clear User-Agent, and keeps the answer with where it
came from. Cities the geocoder cannot place are listed, never guessed. It sends city names only.
"""

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.contracts.queries import CatalogPharmacies, CityLocation, Pharmacy
from pharmavique.catalog.infrastructure.persistence.pharmacies import SqlAlchemyPharmacyReader
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.foundation.geocoding import Geocoded, NominatimGeocoder
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.shared_kernel.geo import distance_km
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.ports import Clock

EXIT_OK = 0
EXIT_NO_DATABASE = 4
EXIT_UNRESOLVED = 2
SOURCE = "openstreetmap-nominatim"
TRUST = "unofficial_unverified"
# Regions are large (the Eastern Province is about 450 km across), so a point more than this far
# from the other cities of its own region is taken for a same-named place elsewhere.
MAX_KM_FROM_REGION = 500.0


class CityGeocoder(Protocol):
    async def city(self, name: str) -> Geocoded | None: ...


@dataclass
class LocateReport:
    located: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    suspect: list[tuple[str, int]] = field(default_factory=list)  # (city, km from its region)
    already: int = 0


def add_arguments(commands: Any) -> None:
    geocode = commands.add_parser(
        "geocode-cities", help="find one point per city that has licensed pharmacies (Nominatim)"
    )
    geocode.add_argument("--market", default="SA", choices=[m.value for m in Market])


async def locate_cities(
    source: CatalogPharmacies,
    save: Callable[[CityLocation], Awaitable[None]],
    geocoder: CityGeocoder,
    clock: Clock,
    market: Market,
) -> LocateReport:
    report = LocateReport()
    stored = await source.city_locations(market)
    known = {loc.city_key for loc in stored}
    pharmacies = await source.pharmacies(market)
    cities = {p.city_key: p.city for p in pharmacies if p.city_key and p.city}
    region_of = _regions(pharmacies)
    points: dict[str, tuple[float, float]] = {
        loc.city_key: (loc.latitude, loc.longitude) for loc in stored
    }

    fresh: dict[str, tuple[str, Geocoded]] = {}
    for key, name in sorted(cities.items()):
        if key in known:
            report.already += 1
            continue
        found = await geocoder.city(f"{name}, Saudi Arabia")
        if found is None:
            report.unresolved.append(name)
        else:
            fresh[key] = (name, found)
            points[key] = (found.latitude, found.longitude)

    for key, (name, found) in fresh.items():
        away = _km_from_region(key, points, region_of)
        if away is not None and away > MAX_KM_FROM_REGION:
            report.suspect.append((name, round(away)))
            continue
        await save(
            CityLocation(
                market=market,
                city_key=key,
                city=name,
                latitude=found.latitude,
                longitude=found.longitude,
                source=SOURCE,
                source_ref=found.source_ref,
                fetched_at=clock.now(),
                trust=TRUST,
            )
        )
        report.located.append(name)
    return report


def _regions(pharmacies: tuple[Pharmacy, ...]) -> dict[str, str]:
    """The region most of a city's pharmacies list (the list's own field, not ours)."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for p in pharmacies:
        if p.city_key and p.region:
            counts[p.city_key][p.region] += 1
    return {key: max(c, key=lambda r: (c[r], r)) for key, c in counts.items()}


def _km_from_region(
    key: str, points: dict[str, tuple[float, float]], region_of: dict[str, str]
) -> float | None:
    """How far a city's point is from the median point of the other cities of its region, or None
    when the region has no other city with a point (nothing to compare with)."""
    region = region_of.get(key)
    if region is None:
        return None
    others = [points[k] for k, r in region_of.items() if r == region and k != key and k in points]
    if not others:
        return None
    centre = (
        statistics.median(lat for lat, _ in others),
        statistics.median(lon for _, lon in others),
    )
    lat, lon = points[key]
    return distance_km(lat, lon, *centre)


async def geocode(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None:
        print("set PHARMAVIQUE_DATABASE_URL first", file=sys.stderr)
        return EXIT_NO_DATABASE
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        reader = SqlAlchemyPharmacyReader(create_session_factory(engine))
        async with httpx.AsyncClient(timeout=30.0) as client:
            geocoder = NominatimGeocoder(client, Throttle(1.1, jitter=0.2))
            report = await locate_cities(
                reader, reader.save_city_location, geocoder, SystemClock(), Market(args.market)
            )
    finally:
        await engine.dispose()
    print(f"located {len(report.located)}, already known {report.already}")
    for name in report.unresolved:
        print(f"  could not place: {name}")
    for name, km in report.suspect:
        print(f"  not saved, {km} km from the other cities of its region: {name}")
    return EXIT_UNRESOLVED if report.unresolved or report.suspect else EXIT_OK
