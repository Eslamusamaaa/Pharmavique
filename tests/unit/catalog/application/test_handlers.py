"""Handler tests run on in-memory fakes of the ports; no database, no framework."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Any, Self

from pharmavique.catalog.application.handlers import (
    ApplyCatalogChangesHandler,
    WithdrawProductsHandler,
)
from pharmavique.catalog.contracts import events as published
from pharmavique.catalog.contracts.commands import (
    ApplyCatalogChanges,
    IngredientLineDto,
    ProductSnapshot,
    WithdrawProducts,
)
from pharmavique.catalog.domain.product import ListingStatus, Product
from pharmavique.catalog.domain.values import ProductId
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.events import IntegrationEvent
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SAR = Currency.owner_assumed("SAR")


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
        "trade_name_ar": None,
        "ingredients": (IngredientLineDto("ACMEDRONE", Decimal("5"), "mg"),),
        "dosage_form_en": "Tablet",
        "dosage_form_ar": None,
        "legal_status": "Prescription",
        "atc_codes": ("A07CA",),
        "price": Money(Decimal(price), SAR) if price is not None else None,
    }
    fields.update(overrides)
    return ProductSnapshot(**fields)


class FakeOutbox:
    def __init__(self) -> None:
        self.events: list[IntegrationEvent] = []

    async def add(self, events: Sequence[IntegrationEvent]) -> None:
        self.events.extend(events)


class FakeProducts:
    def __init__(self, store: dict[ProductId, Product]) -> None:
        self._store = store

    async def get(self, product_id: ProductId) -> Product | None:
        return self._store.get(product_id)

    async def add(self, product: Product) -> None:
        self._store[product.id] = product

    async def save(self, product: Product) -> None:
        self._store[product.id] = product


class FakeUnitOfWork:
    def __init__(self, store: dict[ProductId, Product], outbox: FakeOutbox) -> None:
        self.products = FakeProducts(store)
        self.outbox = outbox
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class Rig:
    """Shared in-memory state plus the two handlers wired to it. Also acts as the clock."""

    def __init__(self) -> None:
        self.store: dict[ProductId, Product] = {}
        self.outbox = FakeOutbox()
        self.units: list[FakeUnitOfWork] = []
        self.current_time = NOW
        self.apply = ApplyCatalogChangesHandler(self.new_unit, self)
        self.withdraw = WithdrawProductsHandler(self.new_unit, self)

    def new_unit(self) -> FakeUnitOfWork:
        unit = FakeUnitOfWork(self.store, self.outbox)
        self.units.append(unit)
        return unit

    def now(self) -> datetime:
        return self.current_time

    def event_types(self) -> list[type]:
        return [type(e) for e in self.outbox.events]


async def test_new_products_are_added_and_announced_in_one_committed_transaction() -> None:
    rig = Rig()

    result = await rig.apply.handle(
        ApplyCatalogChanges((snapshot("a"), snapshot("b")), provenance())
    )

    assert result.added == 2
    assert len(rig.store) == 2
    assert rig.event_types() == [published.ProductAdded, published.ProductAdded]
    assert [u.commits for u in rig.units] == [1]


async def test_the_published_event_uses_plain_values_and_a_schema_version() -> None:
    rig = Rig()

    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"),), provenance()))

    event = rig.outbox.events[0]
    assert isinstance(event, published.ProductAdded)
    assert (event.market, event.register_number) == (Market.SA, "a")
    assert event.price == Money(Decimal("9.5"), SAR)
    assert event.schema_version == 1


async def test_applying_the_same_snapshots_again_is_a_no_op() -> None:
    rig = Rig()
    batch = ApplyCatalogChanges((snapshot("a"), snapshot("b")), provenance())
    await rig.apply.handle(batch)
    events_after_first_run = len(rig.outbox.events)

    rig.current_time = NOW + timedelta(days=1)
    result = await rig.apply.handle(batch)

    assert (result.added, result.unchanged) == (0, 2)
    assert len(rig.outbox.events) == events_after_first_run


async def test_a_new_price_is_reported_as_a_price_change_event() -> None:
    rig = Rig()
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a", "9.5"),), provenance()))
    rig.outbox.events.clear()

    result = await rig.apply.handle(
        ApplyCatalogChanges((snapshot("a", "12"),), provenance("run-2"))
    )

    assert result.price_changed == 1
    (event,) = rig.outbox.events
    assert isinstance(event, published.PriceChanged)
    assert (event.old_price, event.new_price) == (
        Money(Decimal("9.5"), SAR),
        Money(Decimal("12"), SAR),
    )


async def test_changed_details_are_reported_with_the_field_names() -> None:
    rig = Rig()
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"),), provenance()))
    rig.outbox.events.clear()

    result = await rig.apply.handle(
        ApplyCatalogChanges((snapshot("a", dosage_form_en="Capsule"),), provenance("run-2"))
    )

    assert result.details_changed == 1
    (event,) = rig.outbox.events
    assert isinstance(event, published.ProductDetailsChanged)
    assert event.changed_fields == ("dosage_form",)


async def test_the_same_parties_in_another_order_are_not_a_change() -> None:
    from pharmavique.catalog.contracts.commands import PartyDto

    rig = Rig()
    first = snapshot("a", manufacturers=(PartyDto("Maker A", "X"), PartyDto("Maker B", "Y")))
    again = snapshot("a", manufacturers=(PartyDto("Maker B", "Y"), PartyDto("Maker A", "X")))
    await rig.apply.handle(ApplyCatalogChanges((first,), provenance()))

    result = await rig.apply.handle(ApplyCatalogChanges((again,), provenance("run-2")))

    assert result.unchanged == 1


async def test_one_bad_snapshot_is_rejected_and_the_rest_are_still_applied() -> None:
    rig = Rig()
    bad = snapshot("bad", atc_codes=("not-an-atc-code",))

    result = await rig.apply.handle(
        ApplyCatalogChanges((snapshot("a"), bad, snapshot("c")), provenance())
    )

    assert result.added == 2
    assert [r.register_number for r in result.rejected] == ["bad"]
    assert "ATC" in result.rejected[0].reason
    assert sorted(pid.register_number for pid in rig.store) == ["a", "c"]
    assert rig.units[0].commits == 1


async def test_coded_values_are_kept_verbatim_and_recognised_when_known() -> None:
    rig = Rig()

    await rig.apply.handle(
        ApplyCatalogChanges(
            (
                snapshot("a", legal_status="Prescription"),
                snapshot("b", legal_status="Special access"),
            ),
            provenance(),
        )
    )

    known = rig.store[ProductId(Market.SA, "a")].data.legal_status
    unknown = rig.store[ProductId(Market.SA, "b")].data.legal_status
    assert known is not None
    assert (known.raw, known.kind) == ("Prescription", "prescription")
    assert unknown is not None
    assert (unknown.raw, unknown.kind) == ("Special access", None)


async def test_withdrawing_known_products_marks_them_and_announces_it() -> None:
    rig = Rig()
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"), snapshot("b")), provenance()))
    rig.outbox.events.clear()

    result = await rig.withdraw.handle(
        WithdrawProducts(Market.SA, ("a", "missing"), provenance("run-2"))
    )

    assert (result.withdrawn, result.unknown) == (1, 1)
    assert rig.store[ProductId(Market.SA, "a")].listing_status is ListingStatus.WITHDRAWN
    assert rig.store[ProductId(Market.SA, "b")].listing_status is ListingStatus.LISTED
    assert rig.event_types() == [published.ProductWithdrawn]


async def test_withdrawing_twice_does_not_announce_twice() -> None:
    rig = Rig()
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"),), provenance()))
    command = WithdrawProducts(Market.SA, ("a",), provenance("run-2"))
    await rig.withdraw.handle(command)
    rig.outbox.events.clear()

    result = await rig.withdraw.handle(command)

    assert (result.withdrawn, result.already_withdrawn) == (0, 1)
    assert rig.outbox.events == []


async def test_a_withdrawn_product_that_returns_is_announced_as_relisted() -> None:
    rig = Rig()
    await rig.apply.handle(ApplyCatalogChanges((snapshot("a"),), provenance()))
    await rig.withdraw.handle(WithdrawProducts(Market.SA, ("a",), provenance("run-2")))
    rig.outbox.events.clear()

    result = await rig.apply.handle(ApplyCatalogChanges((snapshot("a"),), provenance("run-3")))

    assert result.relisted == 1
    assert rig.event_types() == [published.ProductRelisted]
