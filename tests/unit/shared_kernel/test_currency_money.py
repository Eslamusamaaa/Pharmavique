from decimal import Decimal

import pytest

from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money


def test_markets_are_sa_and_eg() -> None:
    assert {m.value for m in Market} == {"SA", "EG"}


def test_confirmed_currency_keeps_its_code() -> None:
    currency = Currency.confirmed("USD")

    assert currency.code == "USD"
    assert currency.is_confirmed


def test_unconfirmed_currency_has_no_code_and_is_never_assumed() -> None:
    currency = Currency.unconfirmed()

    assert currency.code is None
    assert not currency.is_confirmed


@pytest.mark.parametrize("bad", ["", "us", "usdx", "usd", "U5D", " USD"])
def test_confirmed_currency_rejects_malformed_codes(bad: str) -> None:
    with pytest.raises(InvariantViolation):
        Currency.confirmed(bad)


def test_money_accepts_decimal_amount_with_unconfirmed_currency() -> None:
    money = Money(Decimal("10.50"), Currency.unconfirmed())

    assert money.amount == Decimal("10.50")
    assert not money.currency.is_confirmed


@pytest.mark.parametrize("bad", [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")])
def test_money_rejects_negative_and_non_finite_amounts(bad: Decimal) -> None:
    with pytest.raises(InvariantViolation):
        Money(bad, Currency.unconfirmed())


def test_money_rejects_float_amounts_to_avoid_rounding_surprises() -> None:
    with pytest.raises(InvariantViolation):
        Money(10.5, Currency.unconfirmed())  # type: ignore[arg-type]


def test_money_equality_is_by_value() -> None:
    usd = Currency.confirmed("USD")

    assert Money(Decimal("5"), usd) == Money(Decimal("5.00"), usd)
    assert Money(Decimal("5"), usd) != Money(Decimal("5"), Currency.unconfirmed())
