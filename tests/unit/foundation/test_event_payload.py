import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pharmavique.foundation.events.payload import event_payload
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.events import IntegrationEvent
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, kw_only=True)
class SampleEvent(IntegrationEvent):
    market: Market
    register_number: str
    old_price: Money | None
    new_price: Money | None
    changed_fields: tuple[str, ...]
    count: int
    ratio: Decimal


def sample() -> SampleEvent:
    return SampleEvent(
        event_id=UUID("12345678-1234-5678-1234-567812345678"),
        occurred_at=NOW,
        market=Market.SA,
        register_number="1-111-22",
        old_price=None,
        new_price=Money(Decimal("9.50"), Currency.owner_assumed("SAR")),
        changed_fields=("route", "dosage_form"),
        count=3,
        ratio=Decimal("0.25"),
    )


def test_the_payload_is_plain_json() -> None:
    payload = event_payload(sample())

    assert json.loads(json.dumps(payload)) == payload


def test_envelope_fields_are_not_repeated_in_the_payload() -> None:
    payload = event_payload(sample())

    assert "event_id" not in payload
    assert "occurred_at" not in payload
    assert "schema_version" not in payload


def test_values_are_encoded_without_losing_information() -> None:
    payload = event_payload(sample())

    assert payload["market"] == "SA"
    assert payload["register_number"] == "1-111-22"
    assert payload["old_price"] is None
    assert payload["new_price"] == {
        "amount": "9.50",
        "currency_code": "SAR",
        "currency_basis": "owner_assumption",
    }
    assert payload["changed_fields"] == ["route", "dosage_form"]
    assert payload["count"] == 3
    assert payload["ratio"] == "0.25"
