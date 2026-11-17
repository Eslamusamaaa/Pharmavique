"""The whole path: stored SFDA pages, through ingestion and the catalog, into real Postgres."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.application.handlers import (
    ApplyCatalogChangesHandler,
    WithdrawProductsHandler,
)
from pharmavique.catalog.domain.values import ProductId
from pharmavique.catalog.infrastructure.persistence.models import (
    OutboxRow,
    PricePointRow,
    ProductRow,
)
from pharmavique.catalog.infrastructure.persistence.unit_of_work import (
    SqlAlchemyCatalogUnitOfWork,
)
from pharmavique.catalog.presentation.inprocess import InProcessCatalogCommands
from pharmavique.ingestion.application.load_records import LoadRecordsIntoCatalog
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.adapters.catalog_writer import CatalogWriter
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.ingestion.infrastructure.connectors.sfda_web.stored_records import StoredRecords
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.market import Market

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


def details_html(key: str, **extra: str) -> str:
    fields = {
        "Register Number": key,
        "Trade Name": f"TRADE-{key}",
        "Scientific Name": "ACMEDRONE",
        "Strength": "5",
        "Strength Unit": "mg",
        "Dosage Form": "Tablet",
        "Legal Status": "Prescription",
        "ATC Code 1": "A07CA",
        "Manufacturers": "Name: Maker A | Country: Atlantis",
        "Price": "9.5",
        **extra,
    }
    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in fields.items())
    return f"<table>{rows}</table>"


def save(store: SnapshotStore, key: str, html: str, at: datetime = NOW) -> None:
    page = FetchedPage(f"https://example.test/en/details_data?id={key}", 200, html, at)
    store.save_page(store.details_path("en", key), page)


def load_use_case(session_factory: async_sessionmaker[AsyncSession]) -> LoadRecordsIntoCatalog:
    def unit_of_work() -> SqlAlchemyCatalogUnitOfWork:
        return SqlAlchemyCatalogUnitOfWork(session_factory)

    clock = Clock()
    commands = InProcessCatalogCommands(
        ApplyCatalogChangesHandler(unit_of_work, clock),
        WithdrawProductsHandler(unit_of_work, clock),
    )
    writer = CatalogWriter(
        commands,
        price_currency=Currency.owner_assumed("SAR"),
        snapshot_id="run-1",
        source_ref="https://example.test/en/drugs-list",
        fallback_time=NOW,
    )
    return LoadRecordsIntoCatalog(writer, batch_size=2)


async def count(session_factory: async_sessionmaker[AsyncSession], model: type) -> int:
    async with session_factory() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_stored_pages_reach_postgres_and_loading_again_changes_nothing(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store = SnapshotStore(tmp_path, "run-1")
    save(store, "1-111-22", details_html("1-111-22"))
    save(
        store,
        "2-222-33",
        details_html("2-222-33", **{"Scientific Name": "AAA,BBB", "Strength": "1,2"}),
    )
    save(store, "3-333-44", details_html("3-333-44", **{"Price": "free"}))

    first = await load_use_case(session_factory).run(StoredRecords(store))

    assert (first.records, first.added) == (3, 3)
    assert first.records_with_issues == 1  # the unreadable price was kept as "no price"
    assert await count(session_factory, ProductRow) == 3
    assert await count(session_factory, OutboxRow) == 3

    second = await load_use_case(session_factory).run(StoredRecords(store))

    assert (second.added, second.unchanged) == (0, 3)
    assert await count(session_factory, OutboxRow) == 3
    assert await count(session_factory, PricePointRow) == 2  # the third drug has no price


async def test_a_combination_product_keeps_each_ingredient_with_its_strength(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store = SnapshotStore(tmp_path, "run-1")
    save(store, "k1", details_html("k1", **{"Scientific Name": "AAA,BBB", "Strength": "1,2"}))
    await load_use_case(session_factory).run(StoredRecords(store))

    unit = SqlAlchemyCatalogUnitOfWork(session_factory)
    async with unit as uow:
        product = await uow.products.get(ProductId(Market.SA, "k1"))

    assert product is not None
    assert [(i.name, i.strength) for i in product.data.ingredients] == [
        ("AAA", Decimal("1")),
        ("BBB", Decimal("2")),
    ]
    assert product.data.price is not None
    assert product.data.price.currency.basis.value == "owner_assumption"


async def test_a_later_load_with_a_new_price_records_the_change(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    store = SnapshotStore(tmp_path, "run-1")
    save(store, "k1", details_html("k1"))
    await load_use_case(session_factory).run(StoredRecords(store))

    save(store, "k1", details_html("k1", Price="12"), NOW + timedelta(days=1))
    report = await load_use_case(session_factory).run(StoredRecords(store))

    assert report.price_changed == 1
    assert await count(session_factory, PricePointRow) == 2
    async with session_factory() as session:
        types = (await session.execute(select(OutboxRow.event_type))).scalars().all()
    assert sorted(types) == ["catalog.PriceChanged", "catalog.ProductAdded"]
