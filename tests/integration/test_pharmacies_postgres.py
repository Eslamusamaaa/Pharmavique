"""Pharmacies read from the real list-row table, cities placed once, and the migration."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.contracts.queries import CityLocation
from pharmavique.catalog.infrastructure.persistence.pharmacies import SqlAlchemyPharmacyReader
from pharmavique.shared_kernel.market import Market

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def cells(name: str, phone: str, address: str, region: str) -> str:
    return json.dumps(
        [
            {"label": "Pharmacy Name", "value": name},
            {"label": "Contact Number", "value": phone},
            {"label": "Pharmacy Address", "value": address},
            {"label": "Region", "value": region},
        ]
    )


@pytest.fixture
async def reader(session_factory: async_sessionmaker[AsyncSession]) -> SqlAlchemyPharmacyReader:
    rows = [
        ("k1", cells("Al Dawaa 1", "0138021592", "Dammam - EMAA2513", "Eastern Province")),
        ("k2", cells("Nahdi 2", "", "alkhabar", "Eastern Province")),
        ("k3", cells("Care 3", "0111111111", "RIYADH- RSNA6794", "Riyadh")),
        ("k4", cells("Lost 4", "0122222222", "DMAI8220", "Medina")),
    ]
    async with session_factory() as session, session.begin():
        await session.execute(
            text("TRUNCATE catalog.city_locations, catalog.source_list_links, "
                 "catalog.source_list_rows CASCADE")
        )  # fmt: skip
        for key, value in rows:
            await session.execute(
                text(
                    """
                    INSERT INTO catalog.source_list_rows (
                      list_name, row_key, entity_key, link, cells, list_page,
                      provenance_source, provenance_source_ref, provenance_fetched_at,
                      provenance_snapshot_id, provenance_trust
                    ) VALUES ('pharmacies', :key, :key, NULL, CAST(:cells AS jsonb), 0,
                              'sfda-list-pharmacies', 'https://sfda.example/p?page=0', :now,
                              'lists-1', 'official')
                    """
                ),
                {"key": key, "cells": value, "now": NOW},
            )
    return SqlAlchemyPharmacyReader(session_factory)


async def test_pharmacies_come_with_a_clean_city_the_short_code_and_their_provenance(
    reader: SqlAlchemyPharmacyReader,
) -> None:
    found = {p.name: p for p in await reader.pharmacies(Market.SA)}

    assert len(found) == 4
    dammam = found["Al Dawaa 1"]
    assert (dammam.city, dammam.city_key, dammam.short_code) == ("Dammam", "dammam", "EMAA2513")
    assert dammam.address == "Dammam - EMAA2513"  # exactly as the source wrote it
    assert (dammam.trust, dammam.source_ref) == ("official", "https://sfda.example/p?page=0")
    assert found["Nahdi 2"].city == "Khobar"  # a misspelling joins its city
    assert found["Nahdi 2"].phone is None  # an empty phone is "not given"
    assert found["Care 3"].city == "Riyadh"
    assert found["Lost 4"].city is None  # a bare code has no city
    assert found["Lost 4"].short_code == "DMAI8220"


async def test_a_city_point_is_saved_once_updated_and_read_back(
    reader: SqlAlchemyPharmacyReader,
) -> None:
    first = CityLocation(
        Market.SA, "riyadh", "Riyadh", 24.7, 46.7, "openstreetmap-nominatim", "req-1", NOW,
        "unofficial_unverified",
    )  # fmt: skip
    await reader.save_city_location(first)
    await reader.save_city_location(
        CityLocation(
            Market.SA,
            "riyadh",
            "Riyadh",
            24.71,
            46.68,
            "openstreetmap-nominatim",
            "req-2",
            NOW,
            "unofficial_unverified",
        )
    )

    (stored,) = await reader.city_locations(Market.SA)
    assert (stored.city_key, stored.latitude, stored.source_ref) == ("riyadh", 24.71, "req-2")
    assert stored.trust == "unofficial_unverified"


async def test_the_city_locations_migration_is_reversible(
    migrated_url: URL, make_alembic_config: object
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    await asyncio.to_thread(command.downgrade, config, "catalog_0004")
    await asyncio.to_thread(command.upgrade, config, "catalog@head")
