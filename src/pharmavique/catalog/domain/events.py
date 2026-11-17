"""Domain events of the catalog. They stay inside the context; integration events are separate."""

from dataclasses import dataclass

from pharmavique.catalog.domain.values import ProductId
from pharmavique.shared_kernel.events import DomainEvent
from pharmavique.shared_kernel.money import Money


@dataclass(frozen=True, kw_only=True)
class ProductAdded(DomainEvent):
    product_id: ProductId
    price: Money | None


@dataclass(frozen=True, kw_only=True)
class ProductRelisted(DomainEvent):
    product_id: ProductId


@dataclass(frozen=True, kw_only=True)
class ProductWithdrawn(DomainEvent):
    product_id: ProductId


@dataclass(frozen=True, kw_only=True)
class PriceChanged(DomainEvent):
    product_id: ProductId
    old_price: Money | None
    new_price: Money | None


@dataclass(frozen=True, kw_only=True)
class ProductDetailsChanged(DomainEvent):
    product_id: ProductId
    changed_fields: tuple[str, ...]
