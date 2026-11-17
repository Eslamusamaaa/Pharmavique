"""Ports of the catalog application layer. Adapters live in `infrastructure`."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pharmavique.catalog.domain.product import ListingStatus, Product, ProductData
from pharmavique.catalog.domain.values import ProductId
from pharmavique.shared_kernel.events import IntegrationEvent
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.ports import UnitOfWork


class ConcurrentModification(Exception):
    """Someone else changed the product since this unit of work loaded it. Retry the command."""


class ProductRepository(Protocol):
    async def get(self, product_id: ProductId) -> Product | None: ...

    async def add(self, product: Product) -> None: ...

    async def save(self, product: Product) -> None: ...


@dataclass(frozen=True, slots=True)
class StoredProduct:
    """What the read side needs of a stored product: identity, data and listing status."""

    id: ProductId
    data: ProductData
    listing_status: ListingStatus


class ProductReader(Protocol):
    """Read-only access for queries; no unit of work, no price history."""

    async def get_many(
        self, market: Market, register_numbers: Sequence[str]
    ) -> list[StoredProduct]: ...

    async def page(self, market: Market, after: str | None, limit: int) -> list[StoredProduct]:
        """Products of the market with a register number above `after`, in order."""
        ...


class EventOutbox(Protocol):
    """Writes integration events in the same transaction as the state change."""

    async def add(self, events: Sequence[IntegrationEvent]) -> None: ...


class CatalogUnitOfWork(UnitOfWork, Protocol):
    """One transaction: the repository and the outbox commit or roll back together."""

    @property
    def products(self) -> ProductRepository: ...

    @property
    def outbox(self) -> EventOutbox: ...
