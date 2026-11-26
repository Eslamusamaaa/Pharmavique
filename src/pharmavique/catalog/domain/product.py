"""The Product aggregate: a registered drug product in one market.

Pure domain code. Every operation returns the events it caused; nothing here does I/O.
"""

from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from pharmavique.catalog.domain.events import (
    PriceChanged,
    ProductAdded,
    ProductDetailsChanged,
    ProductRelisted,
    ProductWithdrawn,
)
from pharmavique.catalog.domain.values import (
    AtcCode,
    CodedValue,
    IngredientLine,
    LocalizedText,
    Package,
    Party,
    PricePoint,
    ProductId,
)
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.events import DomainEvent
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance


class ListingStatus(StrEnum):
    LISTED = "listed"
    WITHDRAWN = "withdrawn"  # no longer in the source's public list


@dataclass(frozen=True, slots=True)
class ProductData:
    """Everything the source says about a product, in our terms. `None` means "not stated"."""

    trade_name: LocalizedText
    ingredients: tuple[IngredientLine, ...]
    dosage_form: LocalizedText
    route: LocalizedText | None = None
    package: Package = field(default_factory=Package)
    legal_status: CodedValue | None = None
    product_control: CodedValue | None = None
    distribution_site: CodedValue | None = None
    authorization_status: CodedValue | None = None
    marketing_status: CodedValue | None = None
    atc_codes: tuple[AtcCode, ...] = ()
    shelf_life: str | None = None  # the source does not state the unit
    storage_conditions: LocalizedText | None = None
    manufacturers: tuple[Party, ...] = ()
    marketing_company: Party | None = None
    agents: tuple[str, ...] = ()
    description_code: str | None = None
    price: Money | None = None

    def __post_init__(self) -> None:
        if not self.ingredients:
            raise InvariantViolation("a product needs at least one ingredient line")

    def changed_fields(self, other: "ProductData") -> tuple[str, ...]:
        """Names of the fields that differ, in declaration order. The price is reported apart."""
        return tuple(
            f.name
            for f in fields(self)
            if f.name != "price" and getattr(self, f.name) != getattr(other, f.name)
        )

    def filled_from(self, known: "ProductData") -> tuple["ProductData", tuple[str, ...]]:
        """This data with every value it does not state taken from `known`, and the names of the
        fields that were filled. A load never erases a value the source stopped stating: a renamed
        or missing label on the page reads as "not stated", not as "removed" (audit 2026-11,
        B1.1). Withdrawing a whole product is a separate, guarded step (`withdraw`)."""
        changes: dict[str, Any] = {}
        for f in fields(self):
            new, old = getattr(self, f.name), getattr(known, f.name)
            filled = _fill(new, old)
            if filled is not new:
                changes[f.name] = filled
        if not changes:
            return self, ()
        return replace(self, **changes), tuple(changes)


@dataclass(slots=True)
class Product:
    id: ProductId
    data: ProductData
    listing_status: ListingStatus
    status_changed_at: datetime
    last_seen_at: datetime
    price_history: tuple[PricePoint, ...]
    provenance: Provenance  # provenance of the data as it last changed
    version: int

    @classmethod
    def register(
        cls, product_id: ProductId, data: ProductData, provenance: Provenance, now: datetime
    ) -> tuple["Product", list[DomainEvent]]:
        history = (PricePoint(data.price, now, provenance),) if data.price is not None else ()
        product = cls(
            id=product_id,
            data=data,
            listing_status=ListingStatus.LISTED,
            status_changed_at=now,
            last_seen_at=now,
            price_history=history,
            provenance=provenance,
            version=1,
        )
        event = ProductAdded(occurred_at=now, product_id=product_id, price=data.price)
        return product, [event]

    def apply(self, data: ProductData, provenance: Provenance, now: datetime) -> list[DomainEvent]:
        """Bring the product up to date with a snapshot. Applying the same data again is a no-op.
        Values the snapshot does not state keep their known value (`ProductData.filled_from`)."""
        self.last_seen_at = now
        data, _ = data.filled_from(self.data)
        events: list[DomainEvent] = []

        if self.listing_status is ListingStatus.WITHDRAWN:
            self.listing_status = ListingStatus.LISTED
            self.status_changed_at = now
            events.append(ProductRelisted(occurred_at=now, product_id=self.id))

        changed = self.data.changed_fields(data)
        if changed:
            events.append(
                ProductDetailsChanged(occurred_at=now, product_id=self.id, changed_fields=changed)
            )

        old_price = self.data.price
        if old_price != data.price:
            events.append(
                PriceChanged(
                    occurred_at=now, product_id=self.id, old_price=old_price, new_price=data.price
                )
            )
            if data.price is not None:
                self.price_history = (*self.price_history, PricePoint(data.price, now, provenance))

        if events:
            self.data = data
            self.provenance = provenance
            self.version += 1
        return events

    def withdraw(self, provenance: Provenance, now: datetime) -> list[DomainEvent]:
        if self.listing_status is ListingStatus.WITHDRAWN:
            return []
        self.listing_status = ListingStatus.WITHDRAWN
        self.status_changed_at = now
        self.provenance = provenance
        self.version += 1
        return [ProductWithdrawn(occurred_at=now, product_id=self.id)]


def _fill(new: object, old: object) -> object:
    """`new`, or `old` where `new` states nothing (None, an empty tuple, an empty part of a
    two-language text or a package). Returns `new` itself when nothing is filled."""
    if old is None or new == old:
        return new
    if new is None or new == ():
        return old
    if isinstance(new, LocalizedText) and isinstance(old, LocalizedText):
        if (new.en is None and old.en) or (new.ar is None and old.ar):
            return LocalizedText(new.en or old.en, new.ar or old.ar)
        return new
    if isinstance(new, Package) and isinstance(old, Package):
        parts: dict[str, Any] = {
            f.name: getattr(old, f.name)
            for f in fields(new)
            if getattr(new, f.name) is None and getattr(old, f.name) is not None
        }
        return replace(new, **parts) if parts else new
    return new
