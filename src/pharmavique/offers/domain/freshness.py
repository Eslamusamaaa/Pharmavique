"""How fresh an offer is and how far a retailer can be trusted.

Thresholds are fixed here and shown in the docs, never hidden. Starting values (decisions D-9 and
D-10), tuned from the pilot.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from pharmavique.offers.domain.model import RunStatus

STALE_AFTER = {1: timedelta(days=3), 2: timedelta(days=10)}
HEALTH_RUNS = 14
MINIMUM_RUNS = 3


def is_stale(age: timedelta, tier: int) -> bool:
    return age > STALE_AFTER.get(tier, STALE_AFTER[2])


@dataclass(frozen=True, slots=True)
class RunHealth:
    status: RunStatus
    listings: int
    with_price: int
    parse_errors: int
    anomalies: int


def reliability(runs: Sequence[RunHealth]) -> str:
    """`high`, `medium`, `low`, or `unknown` before three runs, from the last fourteen."""
    recent = list(runs)[-HEALTH_RUNS:]
    if len(recent) < MINIMUM_RUNS:
        return "unknown"
    success = sum(r.status is RunStatus.COMPLETE for r in recent) / len(recent)
    listings = sum(r.listings for r in recent) or 1
    price_coverage = sum(r.with_price for r in recent) / listings
    parse_error_rate = sum(r.parse_errors for r in recent) / listings
    anomaly_rate = sum(r.anomalies for r in recent) / listings
    if (
        success >= 0.9
        and price_coverage >= 0.95
        and parse_error_rate <= 0.02
        and anomaly_rate <= 0.01
    ):
        return "high"
    if success >= 0.7 and price_coverage >= 0.8:
        return "medium"
    return "low"
