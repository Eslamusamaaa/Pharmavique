"""Price anomaly rules: deterministic, no model.

Starting values, tuned from the pilot (decision D-9).

A price that looks wrong is not shown and not stored as current until a second look agrees: the old
price stays. Nothing is ever converted between currencies.
"""

from dataclasses import dataclass
from decimal import Decimal

LARGE_CHANGE = Decimal("0.5")  # more than 50 percent in one step
SLIP_RATIOS = (Decimal(10), Decimal(100), Decimal("0.1"), Decimal("0.01"))
SLIP_TOLERANCE = Decimal("0.02")
CONFIRM_TOLERANCE = Decimal("0.01")
RETAILER_SHIFT_SHARE = Decimal("0.2")
RETAILER_SHIFT_MINIMUM = 50  # fewer listings than this say nothing about the retailer


@dataclass(frozen=True, slots=True)
class PriceVerdict:
    action: str  # "accept", "quarantine", "invalid" or "hold_currency"
    rule: str | None = None


def check_price(
    old: Decimal | None,
    new: Decimal | None,
    old_currency: str | None,
    new_currency: str | None,
) -> PriceVerdict:
    if new is None or new <= 0:
        return PriceVerdict("invalid", "not_a_price")
    if old_currency and new_currency and old_currency != new_currency:
        return PriceVerdict("hold_currency", "currency_change")
    if old is None or old <= 0:
        return PriceVerdict("accept")
    ratio = new / old
    if any(abs(ratio - slip) <= slip * SLIP_TOLERANCE for slip in SLIP_RATIOS):
        return PriceVerdict("quarantine", "decimal_slip")
    if abs(ratio - 1) > LARGE_CHANGE:
        return PriceVerdict("quarantine", "large_change")
    return PriceVerdict("accept")


def confirms(quarantined: Decimal, seen_again: Decimal | None) -> bool:
    """A quarantined price becomes current only when a later look sees the same price."""
    if seen_again is None or quarantined <= 0:
        return False
    return abs(seen_again - quarantined) <= quarantined * CONFIRM_TOLERANCE


def retailer_wide_shift(*, changed: int, total: int) -> bool:
    """More than a fifth of a retailer's listings changing price in one run is a parser or currency
    change until proven otherwise: the run is held for review."""
    if total < RETAILER_SHIFT_MINIMUM:
        return False
    return Decimal(changed) / Decimal(total) > RETAILER_SHIFT_SHARE
