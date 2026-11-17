"""The catalog's use cases running against the real Postgres: repository, outbox, transactions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.application.handlers import (
    ApplyCatalogChangesHandler,
    WithdrawProductsHandler,
)
from pharmavique.catalog.application.ports import ConcurrentModification
from pharmavique.catalog.contracts.commands import (
    ApplyCatalogChanges,
    IngredientLineDto,
    ProductSnapshot,
    WithdrawProducts,
)
from pharmavique.catalog.domain.product import ListingStatus
from pharmavique.catalog.domain.values import ProductId
from pharmavique.catalog.infrastructure.persistence.models import (
    OutboxRow,
    PricePointRow,
    ProductRow,
)
from pharmavique.catalog.infrastructure.persistence.outbox import SqlAlchemyOutbox
from pharmavique.catalog.infrastructure.persistence.unit_of_work import (
    SqlAlchemyCatalogUnitOfWork,
)
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


def provenance(snapshot_id: str = "run-1") -> Provenance:
    return Provenance(
        "sfda-drugs-list-web", "https://example.test", NOW, snapshot_id, TrustLevel.OFFICIAL
    )


def snapshot(
    number: str = "1-111-22", price: str | None = "9.5", **overrides: Any
) -> ProductSnapshot:
    fields: dict[str, Any] = {
        "market": Market.SA,
        "register_number": number,
        "trade_name_en": f"TRADE-{number}",
        "trade_name_ar": "اسم تجاري",
        "ingredients": (IngredientLineDto("ACMEDRONE", Decimal("5"), "mg"),),
        "dosage_form_en": "Tablet",
        "dosage_form_ar": "اقراص",
        "legal_status": "Prescription",
        "atc_codes": ("A07CA",),
        "price": Money(Decimal(price), SAR) if price is not None else None,
    }
    fields.update(overrides)
    return ProductSnapshot(**fields)


class Rig:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.clock = Clock()
        self.apply = ApplyCatalogChangesHandler(self.unit_of_work, self.clock)
        self.withdraw = WithdrawProductsHandler(self.unit_of_work, self.clock)

    def unit_of_work(self) -> SqlAlchemyCatalogUnitOfWork:
        return SqlAlchemyCatalogUnitOfWork(self.session_factory)

    async def count(self, model: type) -> int:
        async with self.session_factory() as session:
            return (await session.execute(select(func.count()).select_from(model))).scalar_one()

    async def outbox_types(self) -> list[str]:
        async with self.session_factory() as session:
            rows = await session.execute(
                select(OutboxRow.event_type).order_by(OutboxRow.occurred_at, OutboxRow.id)
            )
            return [row[0] for row in rows]


@pytest.fixture
def rig(session_factory: async_sessionmaker[AsyncSession]) -> Rig:
    return Rig(session_factory)


async def test_new_products_are_stored_with_their_price_history_and_outbox_events(rig: Rig) -> None:
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"), snapshot("b")), provenance()))

    assert await rig.count(ProductRow) == 2
    assert await rig.count(PricePointRow) == 2
    assert sorted(await rig.outbox_types()) == ["catalog.ProductAdded", "catalog.ProductAdded"]


async def test_a_stored_product_comes_back_equal(rig: Rig) -> None:
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"),), provenance()))

    async with rig.unit_of_work() as uow:
        product = await uow.products.get(ProductId(Market.SA, "a"))

    assert product is not None
    assert product.data.trade_name.ar == "اسم تجاري"
    assert product.data.legal_status is not None
    assert product.data.legal_status.kind == "prescription"
    assert product.data.price == Money(Decimal("9.5"), SAR)
    assert product.listing_status is ListingStatus.LISTED
    assert [p.price for p in product.price_history] == [Money(Decimal("9.5"), SAR)]
    assert product.provenance == provenance()
    assert product.version == 1


async def test_applying_the_same_snapshot_again_adds_no_rows_and_no_events(rig: Rig) -> None:
    batch = ApplyCatalogChanges((snapshot("a"),), provenance())
    await rig.apply.handle(batch)

    rig.clock.current = NOW + timedelta(days=1)
    result = await rig.apply.handle(batch)

    assert result.unchanged == 1
    assert await rig.count(OutboxRow) == 1
    assert await rig.count(PricePointRow) == 1
    async with rig.unit_of_work() as uow:
        product = await uow.products.get(ProductId(Market.SA, "a"))
    assert product is not None
    assert product.version == 1
    assert product.last_seen_at == NOW + timedelta(days=1)


async def test_a_price_change_updates_the_product_and_appends_history(rig: Rig) -> None:
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a", "9.5"),), provenance()))

    rig.clock.current = NOW + timedelta(days=1)
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a", "12"),), provenance("run-2")))

    assert await rig.count(PricePointRow) == 2
    assert "catalog.PriceChanged" in await rig.outbox_types()
    async with rig.unit_of_work() as uow:
        product = await uow.products.get(ProductId(Market.SA, "a"))
    assert product is not None
    assert product.data.price == Money(Decimal("12"), SAR)
    assert [p.price.amount for p in product.price_history] == [Decimal("9.5"), Decimal("12")]
    assert product.version == 2


async def test_the_outbox_row_carries_the_event_envelope_and_a_plain_payload(rig: Rig) -> None:
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"),), provenance()))

    async with rig.session_factory() as session:
        row = (await session.execute(select(OutboxRow))).scalar_one()

    assert row.event_type == "catalog.ProductAdded"
    assert row.schema_version == 1
    assert row.occurred_at == NOW
    assert row.published_at is None
    assert row.payload["register_number"] == "a"
    assert row.payload["market"] == "SA"
    assert row.payload["price"]["currency_basis"] == "owner_assumption"


async def test_a_failure_halfway_leaves_nothing_behind(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(self: SqlAlchemyOutbox, events: object) -> None:
        raise RuntimeError("the outbox is broken")

    monkeypatch.setattr(SqlAlchemyOutbox, "add", boom)

    with pytest.raises(RuntimeError):
        await rig.apply.handle(ApplyCatalogChanges((snapshot("a"), snapshot("b")), provenance()))

    assert await rig.count(ProductRow) == 0
    assert await rig.count(PricePointRow) == 0
    assert await rig.count(OutboxRow) == 0


async def test_withdrawing_marks_the_row_and_writes_an_event(rig: Rig) -> None:
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"),), provenance()))

    result = await rig.withdraw.handle(
        WithdrawProducts(Market.SA, ("a", "missing"), provenance("run-2"))
    )

    assert (result.withdrawn, result.unknown) == (1, 1)
    async with rig.session_factory() as session:
        row = (await session.execute(select(ProductRow))).scalar_one()
    assert row.listing_status == "withdrawn"
    assert "catalog.ProductWithdrawn" in await rig.outbox_types()


async def test_two_writers_cannot_silently_overwrite_each_other(rig: Rig) -> None:
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a", "9.5"),), provenance()))
    product_id = ProductId(Market.SA, "a")

    first = rig.unit_of_work()
    second = rig.unit_of_work()
    async with first as uow1, second as uow2:
        p1 = await uow1.products.get(product_id)
        p2 = await uow2.products.get(product_id)
        assert p1 is not None
        assert p2 is not None
        p1.withdraw(provenance("run-2"), NOW + timedelta(days=1))
        await uow1.products.save(p1)
        await uow1.commit()

        p2.withdraw(provenance("run-3"), NOW + timedelta(days=2))
        with pytest.raises(ConcurrentModification):
            await uow2.products.save(p2)


async def test_the_schema_has_no_foreign_keys_to_other_schemas(engine: Any) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT count(*) FROM information_schema.table_constraints tc "
                "JOIN information_schema.constraint_column_usage ccu "
                "ON tc.constraint_name = ccu.constraint_name "
                "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'catalog' "
                "AND ccu.table_schema <> 'catalog'"
            )
        )
        assert rows.scalar_one() == 0


async def test_the_reader_serves_cards_and_exports_in_pages(
    rig: Rig, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from pharmavique.catalog.application.queries import ReadProductCardsHandler
    from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader

    await rig.apply.handle(
        ApplyCatalogChanges((snapshot("a"), snapshot("b"), snapshot("c")), provenance())
    )
    await rig.withdraw.handle(WithdrawProducts(Market.SA, ("b",), provenance("run-2")))
    queries = ReadProductCardsHandler(SqlAlchemyProductReader(session_factory))

    cards = await queries.get_cards(Market.SA, ("c", "a", "missing"))
    first = await queries.export_cards(Market.SA, None, limit=2)
    second = await queries.export_cards(Market.SA, first.next_after, limit=2)

    assert [c.register_number for c in cards] == ["a", "c"]
    assert cards[0].trade_name_ar == "اسم تجاري"
    assert [c.register_number for c in first.cards] == ["a", "b"]
    assert [c.register_number for c in second.cards] == ["c"]
    assert {c.register_number: c.listing_status for c in first.cards + second.cards} == {
        "a": "listed",
        "b": "withdrawn",
        "c": "listed",
    }
