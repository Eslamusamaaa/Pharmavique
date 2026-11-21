"""The outbox relay source, the last price change and the ingredient lookup, on real Postgres."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.application.handlers import ApplyCatalogChangesHandler
from pharmavique.catalog.contracts.commands import (
    ApplyCatalogChanges,
    IngredientLineDto,
    ProductSnapshot,
)
from pharmavique.catalog.infrastructure.persistence.outbox import SqlAlchemyOutboxPublisher
from pharmavique.catalog.infrastructure.persistence.price_changes import (
    SqlAlchemyIngredientReader,
    SqlAlchemyPriceChangeReader,
)
from pharmavique.catalog.infrastructure.persistence.unit_of_work import (
    SqlAlchemyCatalogUnitOfWork,
)
from pharmavique.foundation.events.relay import OutboxRelay
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.events import StoredEvent
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


def provenance(snapshot_id: str) -> Provenance:
    return Provenance("sfda", "https://example.test", NOW, snapshot_id, TrustLevel.OFFICIAL)


class Rig:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.clock = Clock()
        self.apply = ApplyCatalogChangesHandler(
            lambda: SqlAlchemyCatalogUnitOfWork(session_factory), self.clock
        )

    async def load(self, snapshot_id: str, *items: ProductSnapshot) -> None:
        await self.apply.handle(ApplyCatalogChanges(items, provenance(snapshot_id)))


@pytest.fixture
def rig(session_factory: async_sessionmaker[AsyncSession]) -> Rig:
    return Rig(session_factory)


async def test_the_last_price_change_is_found_only_after_two_different_prices(rig: Rig) -> None:
    reader = SqlAlchemyPriceChangeReader(rig.session_factory)
    await rig.load("run-1", snapshot("a", "5"), snapshot("b", "7"))

    assert await reader.last_change(Market.SA, "a") is None  # one price is not a change

    rig.clock.current = NOW + timedelta(days=1)
    await rig.load("run-2", snapshot("a", "6.5"), snapshot("b", "7"))

    change = await reader.last_change(Market.SA, "a")
    assert change is not None
    assert (change.old_amount, change.new_amount) == (Decimal("5"), Decimal("6.5"))
    assert change.changed_at == NOW + timedelta(days=1)
    assert await reader.last_change(Market.SA, "b") is None  # the price did not move


async def test_the_relay_delivers_each_event_once_in_order_and_marks_it_published(
    rig: Rig,
) -> None:
    await rig.load("run-1", snapshot("a", "5"))
    rig.clock.current = NOW + timedelta(days=1)
    await rig.load("run-2", snapshot("a", "6"))
    seen: list[StoredEvent] = []

    async def collect(event: StoredEvent) -> None:
        seen.append(event)

    relay = OutboxRelay([SqlAlchemyOutboxPublisher(rig.session_factory)], [collect])

    assert await relay.run_until_empty() == 2
    assert [e.event_type for e in seen] == ["catalog.ProductAdded", "catalog.PriceChanged"]
    assert seen[1].payload["register_number"] == "a"
    assert Decimal(seen[1].payload["new_price"]["amount"]) == Decimal("6")
    assert await relay.run_until_empty() == 0  # nothing is delivered twice


async def test_a_failing_subscriber_leaves_the_events_waiting_for_the_next_round(
    rig: Rig,
) -> None:
    await rig.load("run-1", snapshot("a", "5"))

    async def broken(event: StoredEvent) -> None:
        raise RuntimeError("boom")

    relay = OutboxRelay([SqlAlchemyOutboxPublisher(rig.session_factory)], [broken])
    with pytest.raises(RuntimeError, match="boom"):
        await relay.run_once()

    delivered: list[StoredEvent] = []

    async def collect(event: StoredEvent) -> None:
        delivered.append(event)

    again = OutboxRelay([SqlAlchemyOutboxPublisher(rig.session_factory)], [collect])
    assert await again.run_until_empty() == 1
    assert len(delivered) == 1


async def test_ingredient_names_are_found_by_prefix_and_checked_exactly(rig: Rig) -> None:
    await rig.load(
        "run-1",
        snapshot("a", "5", "AMOXICILLIN TRIHYDRATE", "CLAVULANIC ACID"),
        snapshot("b", "5", "AMOXICILLIN"),
        snapshot("c", "5", "PARACETAMOL"),
    )
    reader = SqlAlchemyIngredientReader(rig.session_factory)

    assert await reader.find_ingredients(Market.SA, "amox", 10) == (
        "AMOXICILLIN",
        "AMOXICILLIN TRIHYDRATE",
    )
    assert await reader.find_ingredients(Market.SA, "100%", 10) == ()  # a literal, not a wildcard
    assert await reader.is_ingredient(Market.SA, "paracetamol") is True
    assert await reader.is_ingredient(Market.SA, "para") is False
