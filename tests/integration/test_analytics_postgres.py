"""The analytics read model and the quality counts on real Postgres, fed by the real catalog."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.infrastructure.catalog_source import CatalogMarketSource
from pharmavique.analytics.infrastructure.postgres import PostgresAnalyticsStore
from pharmavique.catalog.application.handlers import ApplyCatalogChangesHandler
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.contracts.commands import (
    ApplyCatalogChanges,
    IngredientLineDto,
    ProductSnapshot,
)
from pharmavique.catalog.infrastructure.persistence.outbox import SqlAlchemyOutboxPublisher
from pharmavique.catalog.infrastructure.persistence.quality import SqlAlchemyQualityReader
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.catalog.infrastructure.persistence.unit_of_work import (
    SqlAlchemyCatalogUnitOfWork,
)
from pharmavique.foundation.events.relay import OutboxRelay
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SAR = Currency.owner_assumed("SAR")


class Clock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


def snapshot(number: str, price: str, *ingredients: str) -> ProductSnapshot:
    lines = ingredients or ("PARACETAMOL",)
    return ProductSnapshot(
        market=Market.SA,
        register_number=number,
        trade_name_en=f"TRADE-{number}",
        trade_name_ar="اسم",
        ingredients=tuple(IngredientLineDto(n, Decimal("5"), "mg") for n in lines),
        dosage_form_en="Tablet",
        dosage_form_ar="اقراص",
        price=Money(Decimal(price), SAR),
    )


class Rig:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory
        self.clock = Clock()
        self.apply = ApplyCatalogChangesHandler(
            lambda: SqlAlchemyCatalogUnitOfWork(factory), self.clock
        )
        self.service = AnalyticsService(
            PostgresAnalyticsStore(factory),
            CatalogMarketSource(ReadProductCardsHandler(SqlAlchemyProductReader(factory))),
            self.clock,
        )
        self.relay = OutboxRelay([SqlAlchemyOutboxPublisher(factory)], [self.service.on_event])

    async def load(self, snapshot_id: str, *items: ProductSnapshot) -> None:
        provenance = Provenance(
            "sfda", "https://example.test", NOW, snapshot_id, TrustLevel.OFFICIAL
        )
        await self.apply.handle(ApplyCatalogChanges(items, provenance))


@pytest.fixture
async def rig(session_factory: async_sessionmaker[AsyncSession]) -> Rig:
    async with session_factory() as session, session.begin():
        await session.execute(
            text(
                "TRUNCATE analytics.market_products, analytics.market_events, "
                "analytics.projection_meta"
            )
        )
    return Rig(session_factory)


async def test_rebuild_then_market_map_gaps_and_the_radar(rig: Rig) -> None:
    await rig.load("run-1", snapshot("a", "5"), snapshot("b", "7", "PARACETAMOL", "CAFFEINE"))
    await rig.relay.run_until_empty()  # nothing is kept before the first rebuild
    rig.clock.current = NOW + timedelta(hours=12)
    assert await rig.service.rebuild(Market.SA) == 2

    rig.clock.current = NOW + timedelta(days=1)
    await rig.load("run-2", snapshot("a", "6.5"), snapshot("b", "7", "PARACETAMOL", "CAFFEINE"))
    assert await rig.relay.run_until_empty() == 1  # the one price change

    market = await rig.service.market_map(Market.SA, "paracetamol")
    assert (market.listed, len(market.groups)) == (2, 2)
    alone = next(g for g in market.groups if g.ingredients == ("PARACETAMOL",))
    assert alone.price_ranges[0].currency_basis == "owner_assumption"

    radar = await rig.service.radar(Market.SA, "paracetamol", 7, 20)
    assert len(radar) == 1  # the first load's events happened before the first rebuild
    item = radar[0]
    assert (item.event.kind.value, item.event.register_number) == ("price_changed", "a")
    assert (item.event.old_price, item.event.new_price) == ("5", "6.5")
    assert item.ingredients == ("PARACETAMOL",)

    assert await rig.service.radar(Market.SA, "caffeine", 7, 20) == []
    status = await rig.service.status(Market.SA)
    assert (status.products, status.events_7d) == (2, 1)


async def test_a_redelivered_event_adds_nothing(rig: Rig) -> None:
    await rig.load("run-1", snapshot("a", "5"))
    rig.clock.current = NOW + timedelta(hours=1)
    await rig.service.rebuild(Market.SA)
    rig.clock.current = NOW + timedelta(days=1)
    await rig.load("run-2", snapshot("a", "9"))
    store = PostgresAnalyticsStore(rig.factory)
    events = await store.radar("SA", None, NOW, 10)
    assert events == []  # not relayed yet
    await rig.relay.run_until_empty()
    (first,) = await store.radar("SA", None, NOW, 10)
    assert await store.add_event(first.event) is False
    assert len(await store.radar("SA", None, NOW, 10)) == 1


async def test_a_rebuild_replaces_rows_and_keeps_the_first_build_time(rig: Rig) -> None:
    await rig.load("run-1", snapshot("a", "5"))
    rig.clock.current = NOW + timedelta(hours=1)
    await rig.service.rebuild(Market.SA)
    await rig.load("run-1b", snapshot("a", "5"), snapshot("c", "8"))
    rig.clock.current = NOW + timedelta(hours=5)
    assert await rig.service.rebuild(Market.SA) == 2
    status = await rig.service.status(Market.SA)
    assert status.products == 2
    assert status.first_built_at == NOW + timedelta(hours=1)
    assert status.built_at == NOW + timedelta(hours=5)


async def test_quality_counts_what_is_missing(rig: Rig) -> None:
    await rig.load("run-1", snapshot("a", "5"), snapshot("b", "7"))
    stats = await SqlAlchemyQualityReader(rig.factory).quality_stats(Market.SA)
    assert (stats.products, stats.listed, stats.withdrawn) == (2, 2, 0)
    assert stats.listed_without_price == 0
    assert stats.listed_without_ingredients == 0
    assert stats.listed_with_missing_strength == 0
    assert stats.listed_without_manufacturer == 2
    assert (stats.listed_with_real_picture, stats.listed_without_picture) == (0, 2)
    assert stats.lists == ()


async def test_the_analytics_migration_is_reversible(
    migrated_url: URL, make_alembic_config: object
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    await asyncio.to_thread(command.downgrade, config, "analytics@base")
    await asyncio.to_thread(command.upgrade, config, "analytics@head")
