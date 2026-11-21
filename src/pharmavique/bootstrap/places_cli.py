"""`pharmavique geocode-cities`: find one point for each city that has licensed pharmacies.

Run once (and again when a new city appears in the pharmacy list): it looks up only the cities that
have no point yet, one request a second, with a clear User-Agent, and keeps the answer with where it
came from. Cities the geocoder cannot place are listed, never guessed. It sends city names only.
"""

import argparse
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import httpx

from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.contracts.queries import CatalogPharmacies, CityLocation
from pharmavique.catalog.infrastructure.persistence.pharmacies import SqlAlchemyPharmacyReader
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.foundation.geocoding import Geocoded, NominatimGeocoder
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.ports import Clock

EXIT_OK = 0
EXIT_NO_DATABASE = 4
EXIT_UNRESOLVED = 2
SOURCE = "openstreetmap-nominatim"
TRUST = "unofficial_unverified"


class CityGeocoder(Protocol):
    async def city(self, name: str) -> Geocoded | None: ...


@dataclass
class LocateReport:
    located: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
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
    known = {loc.city_key for loc in await source.city_locations(market)}
    cities = {p.city_key: p.city for p in await source.pharmacies(market) if p.city_key and p.city}
    now: datetime
    for key, name in sorted(cities.items()):
        if key in known:
            report.already += 1
            continue
        found = await geocoder.city(f"{name}, Saudi Arabia")
        if found is None:
            report.unresolved.append(name)
            continue
        now = clock.now()
        await save(
            CityLocation(
                market=market,
                city_key=key,
                city=name,
                latitude=found.latitude,
                longitude=found.longitude,
                source=SOURCE,
                source_ref=found.source_ref,
                fetched_at=now,
                trust=TRUST,
            )
        )
        report.located.append(name)
    return report


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
    return EXIT_UNRESOLVED if report.unresolved else EXIT_OK
