"""Turn an integration event into a JSON-compatible payload for the outbox.

The envelope (id, time, schema version) is stored in its own columns, so the payload holds only
the event's own fields. Decimals become text so no precision is lost.
"""

from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pharmavique.shared_kernel.events import IntegrationEvent
from pharmavique.shared_kernel.money import Money

_ENVELOPE = frozenset({"event_id", "occurred_at", "schema_version"})


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Money):
        return {
            "amount": str(value.amount),
            "currency_code": value.currency.code,
            "currency_basis": value.currency.basis.value,
        }
    if isinstance(value, tuple | list | frozenset):
        return [_encode(item) for item in value]
    raise TypeError(f"cannot put a {type(value).__name__} in an event payload")


def event_payload(event: IntegrationEvent) -> dict[str, Any]:
    return {
        f.name: _encode(getattr(event, f.name)) for f in fields(event) if f.name not in _ENVELOPE
    }
