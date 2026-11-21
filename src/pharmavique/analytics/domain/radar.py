"""What changed in the registry: the competitor radar's events (new, withdrawn, relisted,
repriced)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ChangeKind(StrEnum):
    ADDED = "added"
    RELISTED = "relisted"
    WITHDRAWN = "withdrawn"
    PRICE_CHANGED = "price_changed"


@dataclass(frozen=True, slots=True)
class MarketEvent:
    """One registry change, kept once per integration event (the event id is the key)."""

    event_id: UUID
    market: str
    kind: ChangeKind
    register_number: str
    occurred_at: datetime
    old_price: str | None = None
    new_price: str | None = None
    currency_code: str | None = None
    currency_basis: str | None = None


@dataclass(frozen=True, slots=True)
class RadarItem:
    """A change joined with what the read model knows about the product today."""

    event: MarketEvent
    trade_name_en: str | None
    trade_name_ar: str | None
    marketing_company: str | None
    ingredients: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectionStatus:
    products: int
    built_at: datetime | None
    first_built_at: datetime | None
    events_7d: int
