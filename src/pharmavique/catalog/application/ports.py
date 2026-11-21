"""Ports of the catalog application layer. Adapters live in `infrastructure`."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pharmavique.catalog.domain.product import ListingStatus, Product, ProductData
from pharmavique.catalog.domain.values import ProductId
from pharmavique.shared_kernel.events import IntegrationEvent
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.ports import UnitOfWork
from pharmavique.shared_kernel.provenance import Provenance


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
    provenance: Provenance | None = None  # filled by readers that load it (the detail view)


class ProductReader(Protocol):
    """Read-only access for queries; no unit of work, no price history."""

    async def get_many(
        self, market: Market, register_numbers: Sequence[str]
    ) -> list[StoredProduct]: ...

    async def page(self, market: Market, after: str | None, limit: int) -> list[StoredProduct]:
        """Products of the market with a register number above `after`, in order."""
        ...

    async def with_ingredient_set(
        self, market: Market, names: Sequence[str], limit: int
    ) -> list[StoredProduct]:
        """Products whose ingredient names, compared case-insensitively, are exactly `names`."""
        ...


@dataclass(frozen=True, slots=True)
class PricePair:
    old_amount: Decimal
    old_currency_code: str | None
    old_currency_basis: str
    new_amount: Decimal
    new_currency_code: str | None
    new_currency_basis: str
    changed_at: datetime


class PriceChangeReader(Protocol):
    async def last_change(self, market: Market, register_number: str) -> PricePair | None:
        """The latest change between two different recorded prices, or None when there is none."""
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
