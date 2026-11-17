"""Integration events the catalog publishes (published language, versioned).

Flat messages of plain values. They never carry domain objects. Subscribers must be idempotent and
tolerate re-delivery; each event has an id, a time and a schema version.
"""

from dataclasses import dataclass

from pharmavique.shared_kernel.events import IntegrationEvent
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money


@dataclass(frozen=True, kw_only=True)
class ProductAdded(IntegrationEvent):
    market: Market
    register_number: str
    price: Money | None


@dataclass(frozen=True, kw_only=True)
class ProductRelisted(IntegrationEvent):
    market: Market
    register_number: str


@dataclass(frozen=True, kw_only=True)
class ProductWithdrawn(IntegrationEvent):
    market: Market
    register_number: str


@dataclass(frozen=True, kw_only=True)
class PriceChanged(IntegrationEvent):
    market: Market
    register_number: str
    old_price: Money | None
    new_price: Money | None


@dataclass(frozen=True, kw_only=True)
class ProductDetailsChanged(IntegrationEvent):
    market: Market
    register_number: str
    changed_fields: tuple[str, ...]
