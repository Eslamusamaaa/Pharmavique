"""How long historical and temporary scraping data is kept. Defaults are decision D-5 of the plan.

Raw pages are never kept in the database at all; they live in a short-lived workflow artifact.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from pharmavique.offers.domain.model import ListingCategory


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    price_points_medicine_days: int = 180  # then one row per listing per month
    price_points_other_days: int = 90  # cosmetics and devices
    run_rows_days: int = 90  # then weekly counters
    failed_detail_days: int = 30
    anomaly_after_resolve_days: int = 30
    discontinued_days: int = 365


@dataclass(frozen=True, slots=True)
class Cutoffs:
    price_points_medicine: datetime
    price_points_other: datetime
    run_rows: datetime
    failed_detail: datetime
    anomalies_after_resolve: datetime
    discontinued: datetime

    def price_cutoff(self, category: ListingCategory) -> datetime:
        if category is ListingCategory.MEDICINE:
            return self.price_points_medicine
        return self.price_points_other


def cutoffs(policy: RetentionPolicy, now: datetime) -> Cutoffs:
    return Cutoffs(
        price_points_medicine=now - timedelta(days=policy.price_points_medicine_days),
        price_points_other=now - timedelta(days=policy.price_points_other_days),
        run_rows=now - timedelta(days=policy.run_rows_days),
        failed_detail=now - timedelta(days=policy.failed_detail_days),
        anomalies_after_resolve=now - timedelta(days=policy.anomaly_after_resolve_days),
        discontinued=now - timedelta(days=policy.discontinued_days),
    )
