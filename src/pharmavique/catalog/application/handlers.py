"""Use cases of the catalog (write side). One unit of work per command."""

from collections.abc import Callable

from pharmavique.catalog.application.ports import CatalogUnitOfWork
from pharmavique.catalog.application.translate import snapshot_to_data, to_integration_events
from pharmavique.catalog.contracts.commands import (
    ApplyCatalogChanges,
    ApplyCatalogChangesResult,
    RejectedSnapshot,
    WithdrawProducts,
    WithdrawProductsResult,
)
from pharmavique.catalog.domain import events as domain
from pharmavique.catalog.domain.product import Product
from pharmavique.catalog.domain.values import ProductId
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.events import DomainEvent
from pharmavique.shared_kernel.ports import Clock


class ApplyCatalogChangesHandler:
    def __init__(self, unit_of_work: Callable[[], CatalogUnitOfWork], clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def handle(self, command: ApplyCatalogChanges) -> ApplyCatalogChangesResult:
        added = relisted = details_changed = price_changed = unchanged = 0
        rejected: list[RejectedSnapshot] = []
        now = self._clock.now()

        async with self._unit_of_work() as uow:
            for snapshot in command.snapshots:
                try:
                    product_id = ProductId(snapshot.market, snapshot.register_number)
                    data = snapshot_to_data(snapshot)
                except InvariantViolation as error:
                    rejected.append(RejectedSnapshot(snapshot.register_number, str(error)))
                    continue

                existing = await uow.products.get(product_id)
                events: list[DomainEvent]
                if existing is None:
                    product, events = Product.register(product_id, data, command.provenance, now)
                    await uow.products.add(product)
                else:
                    events = existing.apply(data, command.provenance, now)
                    await uow.products.save(existing)  # keeps "last seen" current

                if events:
                    await uow.outbox.add(to_integration_events(events))
                else:
                    unchanged += 1
                added += sum(isinstance(e, domain.ProductAdded) for e in events)
                relisted += sum(isinstance(e, domain.ProductRelisted) for e in events)
                details_changed += sum(isinstance(e, domain.ProductDetailsChanged) for e in events)
                price_changed += sum(isinstance(e, domain.PriceChanged) for e in events)

            await uow.commit()

        return ApplyCatalogChangesResult(
            added=added,
            relisted=relisted,
            details_changed=details_changed,
            price_changed=price_changed,
            unchanged=unchanged,
            rejected=tuple(rejected),
        )


class WithdrawProductsHandler:
    def __init__(self, unit_of_work: Callable[[], CatalogUnitOfWork], clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def handle(self, command: WithdrawProducts) -> WithdrawProductsResult:
        withdrawn = already_withdrawn = unknown = 0
        now = self._clock.now()

        async with self._unit_of_work() as uow:
            for register_number in command.register_numbers:
                try:
                    product_id = ProductId(command.market, register_number)
                except InvariantViolation:
                    unknown += 1
                    continue
                product = await uow.products.get(product_id)
                if product is None:
                    unknown += 1
                    continue
                events = product.withdraw(command.provenance, now)
                if not events:
                    already_withdrawn += 1
                    continue
                await uow.products.save(product)
                await uow.outbox.add(to_integration_events(events))
                withdrawn += 1
            await uow.commit()

        return WithdrawProductsResult(
            withdrawn=withdrawn, already_withdrawn=already_withdrawn, unknown=unknown
        )
