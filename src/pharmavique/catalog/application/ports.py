"""Ports of the catalog application layer. Adapters live in `infrastructure`."""

from collections.abc import Sequence
from typing import Protocol

from pharmavique.catalog.domain.product import Product
from pharmavique.catalog.domain.values import ProductId
from pharmavique.shared_kernel.events import IntegrationEvent
from pharmavique.shared_kernel.ports import UnitOfWork


class ConcurrentModification(Exception):
    """Someone else changed the product since this unit of work loaded it. Retry the command."""


class ProductRepository(Protocol):
    async def get(self, product_id: ProductId) -> Product | None: ...

    async def add(self, product: Product) -> None: ...

    async def save(self, product: Product) -> None: ...


class EventOutbox(Protocol):
    """Writes integration events in the same transaction as the state change."""

    async def add(self, events: Sequence[IntegrationEvent]) -> None: ...


class CatalogUnitOfWork(UnitOfWork, Protocol):
    """One transaction: the repository and the outbox commit or roll back together."""

    @property
    def products(self) -> ProductRepository: ...

    @property
    def outbox(self) -> EventOutbox: ...
