from decimal import Decimal

import pytest

from pharmavique.shared_kernel.currency import Currency, CurrencyBasis
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


# ---- currency basis: how we know the currency -------------------------------------------------


def test_each_currency_says_how_it_is_known() -> None:
    assert Currency.confirmed("USD").basis is CurrencyBasis.SOURCE_STATED
    assert Currency.owner_assumed("SAR").basis is CurrencyBasis.OWNER_ASSUMPTION
    assert Currency.unconfirmed().basis is CurrencyBasis.UNCONFIRMED


def test_an_owner_assumed_currency_has_a_code_but_is_not_source_confirmed() -> None:
    currency = Currency.owner_assumed("SAR")

    assert currency.code == "SAR"
    assert not currency.is_confirmed


@pytest.mark.parametrize("bad", ["", "sa", "SARX", "sar"])
def test_owner_assumed_currency_rejects_malformed_codes(bad: str) -> None:
    with pytest.raises(InvariantViolation):
        Currency.owner_assumed(bad)


def test_same_code_with_a_different_basis_is_a_different_currency() -> None:
    assert Currency.owner_assumed("SAR") != Currency.confirmed("SAR")


def test_a_currency_without_a_code_cannot_claim_a_basis() -> None:
    with pytest.raises(InvariantViolation):
        Currency(None, CurrencyBasis.OWNER_ASSUMPTION)


def test_a_currency_with_a_code_cannot_be_unconfirmed() -> None:
    with pytest.raises(InvariantViolation):
        Currency("SAR", CurrencyBasis.UNCONFIRMED)
