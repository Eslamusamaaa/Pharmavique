"""The analytics service: rebuilding, idempotent events, and the cutoff at the first rebuild."""

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.domain.market import IngredientLine, MarketProduct
from pharmavique.analytics.domain.radar import MarketEvent, ProjectionStatus, RadarItem
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.events import StoredEvent
from pharmavique.shared_kernel.market import Market

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


def row(number: str, name: str = "Paracetamol") -> MarketProduct:
    return MarketProduct(
        "SA", number, f"T{number}", None, (IngredientLine(name, "500", "MG"),),
        "TABLET", "Acme", "listed", Decimal("10"), "SAR", "source_stated",
    )  # fmt: skip


class Source:
    def __init__(self, rows: list[MarketProduct]) -> None:
        self.rows = rows

    async def pages(self, market: Market, page_size: int) -> AsyncIterator[Sequence[MarketProduct]]:
        for start in range(0, len(self.rows), 2):
            yield self.rows[start : start + 2]


class Store:
    def __init__(self) -> None:
        self.products: list[MarketProduct] = []
        self.built: datetime | None = None
        self.first: datetime | None = None
        self.events: dict[UUID, MarketEvent] = {}

    async def replace_products(
        self, market: str, products: Sequence[MarketProduct], built_at: datetime
    ) -> None:
        self.products = list(products)
        self.built = built_at
        self.first = self.first or built_at

    async def products_with_ingredient(
        self, market: str, ingredient: str, limit: int
    ) -> list[MarketProduct]:
        return [p for p in self.products if ingredient in p.combination]

    async def add_event(self, event: MarketEvent) -> bool:
        if event.event_id in self.events:
            return False
        self.events[event.event_id] = event
        return True

    async def radar(
        self, market: str, ingredient: str | None, since: datetime, limit: int
    ) -> list[RadarItem]:
        return []

    async def first_built_at(self, market: str) -> datetime | None:
        return self.first

    async def status(self, market: str, now: datetime) -> ProjectionStatus:
        return ProjectionStatus(len(self.products), self.built, self.first, len(self.events))


def event(kind: str, when: datetime, payload: Mapping[str, object] | None = None) -> StoredEvent:
    body: dict[str, object] = {"market": "SA", "register_number": "1"}
    body.update(payload or {})
    return StoredEvent(uuid4(), kind, 1, when, body)


@pytest.fixture
def store() -> Store:
    return Store()


@pytest.fixture
def service(store: Store) -> AnalyticsService:
    return AnalyticsService(store, Source([row("1"), row("2"), row("3")]), Clock())


async def test_rebuild_reads_every_page(service: AnalyticsService, store: Store) -> None:
    assert await service.rebuild(Market.SA) == 3
    assert len(store.products) == 3
    assert store.built == NOW


async def test_events_before_the_first_rebuild_are_not_kept(
    service: AnalyticsService, store: Store
) -> None:
    await service.on_event(event("catalog.ProductAdded", NOW))
    assert store.events == {}


async def test_events_older_than_the_first_rebuild_are_not_counted(
    service: AnalyticsService, store: Store
) -> None:
    await service.rebuild(Market.SA)
    await service.on_event(event("catalog.ProductAdded", NOW - timedelta(hours=2)))
    assert store.events == {}
    await service.on_event(event("catalog.ProductAdded", NOW + timedelta(hours=2)))
    assert len(store.events) == 1


async def test_a_delivered_twice_event_is_kept_once(
    service: AnalyticsService, store: Store
) -> None:
    await service.rebuild(Market.SA)
    same = event("catalog.ProductWithdrawn", NOW + timedelta(days=1))
    await service.on_event(same)
    await service.on_event(same)
    assert len(store.events) == 1


async def test_price_change_keeps_old_and_new_amounts(
    service: AnalyticsService, store: Store
) -> None:
    await service.rebuild(Market.SA)
    price = {
        "old_price": {"amount": "10.5", "currency_code": "SAR", "currency_basis": "source_stated"},
        "new_price": {"amount": "12", "currency_code": "SAR", "currency_basis": "source_stated"},
    }
    await service.on_event(event("catalog.PriceChanged", NOW + timedelta(days=1), price))
    (kept,) = store.events.values()
    assert (kept.old_price, kept.new_price, kept.currency_code) == ("10.5", "12", "SAR")


async def test_other_event_types_are_ignored(service: AnalyticsService, store: Store) -> None:
    await service.rebuild(Market.SA)
    await service.on_event(event("catalog.ProductDetailsChanged", NOW + timedelta(days=1)))
    assert store.events == {}


async def test_market_map_for_an_ingredient(service: AnalyticsService) -> None:
    await service.rebuild(Market.SA)
    result = await service.market_map(Market.SA, "paracetamol")
    assert result.listed == 3


async def test_a_too_short_ingredient_is_refused(service: AnalyticsService) -> None:
    with pytest.raises(InvariantViolation):
        await service.market_map(Market.SA, " a ")


async def test_radar_days_are_bounded(service: AnalyticsService) -> None:
    with pytest.raises(InvariantViolation):
        await service.radar(Market.SA, None, 0, 10)
    with pytest.raises(InvariantViolation):
        await service.radar(Market.SA, None, 4000, 10)
