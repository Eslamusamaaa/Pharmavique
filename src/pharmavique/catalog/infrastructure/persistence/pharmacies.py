"""Licensed pharmacies (from the SFDA list rows) and the point found for each city."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.contracts.queries import CityLocation, Pharmacy
from pharmavique.catalog.domain.pharmacies import canonical_city, parse_address
from pharmavique.shared_kernel.market import Market

LIST_NAME = "pharmacies"


def _cells(raw: Sequence[Any]) -> dict[str, str]:
    return {str(c.get("label", "")): str(c.get("value", "")).strip() for c in raw}


class SqlAlchemyPharmacyReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def pharmacies(self, market: Market) -> tuple[Pharmacy, ...]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT cells, provenance_source_ref, provenance_fetched_at,
                               provenance_trust
                        FROM catalog.source_list_rows
                        WHERE list_name = :list_name
                        ORDER BY row_key
                        """
                    ),
                    {"list_name": LIST_NAME},
                )
            ).all()
        found = []
        for row in rows:
            cells = _cells(row.cells)
            name = cells.get("Pharmacy Name", "")
            if not name:
                continue
            address = cells.get("Pharmacy Address", "")
            parsed = parse_address(address)
            city = canonical_city(parsed.city_raw)
            found.append(
                Pharmacy(
                    market=market,
                    name=name,
                    phone=cells.get("Contact Number") or None,
                    region=cells.get("Region") or None,
                    city_key=city.key if city else None,
                    city=city.name if city else None,
                    short_code=parsed.short_code,
                    address=address,
                    source_ref=row.provenance_source_ref,
                    fetched_at=row.provenance_fetched_at,
                    trust=row.provenance_trust,
                )
            )
        return tuple(found)

    async def city_locations(self, market: Market) -> tuple[CityLocation, ...]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT * FROM catalog.city_locations WHERE market = :m ORDER BY city_key"
                    ),
                    {"m": market.value},
                )
            ).all()
        return tuple(
            CityLocation(
                market=market,
                city_key=r.city_key,
                city=r.city,
                latitude=r.latitude,
                longitude=r.longitude,
                source=r.source,
                source_ref=r.source_ref,
                fetched_at=r.fetched_at,
                trust=r.trust,
            )
            for r in rows
        )

    async def save_city_location(self, location: CityLocation) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO catalog.city_locations (
                      market, city_key, city, latitude, longitude, source, source_ref,
                      fetched_at, trust
                    ) VALUES (:market, :city_key, :city, :lat, :lon, :source, :source_ref,
                              :fetched_at, :trust)
                    ON CONFLICT (market, city_key) DO UPDATE SET
                      city = EXCLUDED.city, latitude = EXCLUDED.latitude,
                      longitude = EXCLUDED.longitude, source = EXCLUDED.source,
                      source_ref = EXCLUDED.source_ref, fetched_at = EXCLUDED.fetched_at,
                      trust = EXCLUDED.trust
                    """
                ),
                {
                    "market": location.market.value,
                    "city_key": location.city_key,
                    "city": location.city,
                    "lat": location.latitude,
                    "lon": location.longitude,
                    "source": location.source,
                    "source_ref": location.source_ref,
                    "fetched_at": location.fetched_at,
                    "trust": location.trust,
                },
            )
