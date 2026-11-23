from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pharmavique.offers.domain.anomaly import check_price, confirms, retailer_wide_shift
from pharmavique.offers.domain.freshness import RunHealth, is_stale, reliability
from pharmavique.offers.domain.model import ListingCategory, RunStatus
from pharmavique.offers.domain.retention import RetentionPolicy, cutoffs

D = Decimal


def test_a_first_price_is_accepted() -> None:
    assert check_price(None, D("19.5"), "SAR", "SAR").action == "accept"


def test_a_missing_zero_or_negative_price_is_not_a_price() -> None:
    for bad in (None, D("0"), D("-3")):
        assert check_price(D("10"), bad, "SAR", "SAR").action == "invalid"


def test_a_small_change_is_accepted() -> None:
    assert check_price(D("100"), D("120"), "SAR", "SAR").action == "accept"
    assert check_price(D("100"), D("50"), "SAR", "SAR").action == "accept"


def test_a_change_of_more_than_half_waits_for_a_second_look() -> None:
    result = check_price(D("100"), D("151"), "SAR", "SAR")

    assert (result.action, result.rule) == ("quarantine", "large_change")


def test_a_decimal_slip_is_quarantined_with_its_own_rule() -> None:
    for new in (D("1000"), D("10"), D("10000"), D("1")):
        assert check_price(D("100"), new, "SAR", "SAR").rule == "decimal_slip"


def test_a_currency_change_holds_the_run_and_is_never_converted() -> None:
    assert check_price(D("10"), D("10"), "SAR", "AED").action == "hold_currency"
    assert check_price(D("10"), D("10"), None, "SAR").action == "accept"


def test_a_quarantined_price_is_confirmed_only_by_the_same_price_again() -> None:
    assert confirms(D("151"), D("151"))
    assert confirms(D("151"), D("151.5"))
    assert not confirms(D("151"), D("100"))
    assert not confirms(D("151"), None)


def test_a_shift_across_a_fifth_of_a_retailer_holds_the_run() -> None:
    assert retailer_wide_shift(changed=21, total=100)
    assert not retailer_wide_shift(changed=20, total=100)
    assert not retailer_wide_shift(changed=30, total=40)  # too few listings to say


def test_an_offer_is_stale_after_three_days_for_tier_one_and_ten_for_tier_two() -> None:
    assert not is_stale(timedelta(days=3), 1)
    assert is_stale(timedelta(days=3, seconds=1), 1)
    assert not is_stale(timedelta(days=10), 2)
    assert is_stale(timedelta(days=11), 2)


def good(status: RunStatus = RunStatus.COMPLETE) -> RunHealth:
    return RunHealth(status, listings=1000, with_price=990, parse_errors=5, anomalies=2)


def test_a_retailer_with_few_runs_is_unknown() -> None:
    assert reliability([good(), good()]) == "unknown"


def test_clean_complete_runs_are_high() -> None:
    assert reliability([good()] * 14) == "high"


def test_some_failures_or_missing_prices_lower_the_label() -> None:
    mixed = [good()] * 9 + [good(RunStatus.PARTIAL)] * 3
    assert reliability(mixed) == "medium"
    no_prices = [RunHealth(RunStatus.COMPLETE, 1000, 500, 0, 0)] * 10
    assert reliability(no_prices) == "low"
    assert reliability([good(RunStatus.FAILED)] * 10) == "low"


def test_only_the_last_fourteen_runs_count() -> None:
    old_bad = [good(RunStatus.FAILED)] * 20
    assert reliability(old_bad + [good()] * 14) == "high"


NOW = datetime(2026, 11, 23, tzinfo=UTC)


def test_default_retention_windows() -> None:
    found = cutoffs(RetentionPolicy(), NOW)

    assert found.price_points_medicine == NOW - timedelta(days=180)
    assert found.price_points_other == NOW - timedelta(days=90)
    assert found.run_rows == NOW - timedelta(days=90)
    assert found.failed_detail == NOW - timedelta(days=30)
    assert found.anomalies_after_resolve == NOW - timedelta(days=30)
    assert found.discontinued == NOW - timedelta(days=365)


def test_cosmetics_and_devices_keep_less_price_history() -> None:
    found = cutoffs(RetentionPolicy(), NOW)

    assert found.price_cutoff(ListingCategory.MEDICINE) == found.price_points_medicine
    for category in (ListingCategory.COSMETIC, ListingCategory.DEVICE):
        assert found.price_cutoff(category) == found.price_points_other
