from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.substitution.domain.strength import Quantity, Strength, Unit


def q(amount: str, unit: Unit) -> Quantity:
    return Quantity(Decimal(amount), unit)


def plain(amount: str, unit: Unit) -> Strength:
    return Strength(q(amount, unit))


def conc(amount: str, unit: Unit, per_amount: str, per_unit: Unit) -> Strength:
    return Strength(q(amount, unit), per=q(per_amount, per_unit))


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (plain("500", Unit.MG), plain("0.5", Unit.G)),
        (plain("500", Unit.MG), plain("500000", Unit.MCG)),
        (plain("0.25", Unit.G), plain("250", Unit.MG)),
        (plain("1000", Unit.IU), plain("1000", Unit.IU)),
        (conc("250", Unit.MG, "5", Unit.ML), conc("50", Unit.MG, "1", Unit.ML)),
        (conc("250", Unit.MG, "5", Unit.ML), conc("0.05", Unit.G, "1", Unit.ML)),
        (conc("1", Unit.G, "1", Unit.L), conc("1", Unit.MG, "1", Unit.ML)),
        (conc("125", Unit.MG, "5", Unit.ML), conc("25", Unit.MG, "1", Unit.ML)),
    ],
)
def test_equal_strengths_normalize_to_the_same_value(left: Strength, right: Strength) -> None:
    assert left.normalized() == right.normalized()


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (plain("500", Unit.MG), plain("5", Unit.G)),
        (plain("500", Unit.MG), plain("500", Unit.MCG)),
        (plain("500", Unit.MG), plain("500", Unit.IU)),  # mass is never an international unit
        (plain("5", Unit.MG), conc("5", Unit.MG, "1", Unit.ML)),  # total dose vs concentration
        (conc("250", Unit.MG, "5", Unit.ML), conc("250", Unit.MG, "10", Unit.ML)),
        (conc("1", Unit.MG, "1", Unit.ML), conc("1", Unit.MG, "1", Unit.L)),
    ],
)
def test_different_strengths_never_normalize_equal(left: Strength, right: Strength) -> None:
    assert left.normalized() != right.normalized()


def test_normalization_is_exact_for_non_terminating_ratios() -> None:
    # 1 mg / 3 ml has no finite decimal expansion; three of them must equal 1 mg / 1 ml exactly.
    third = conc("1", Unit.MG, "3", Unit.ML).normalized().value
    assert third * 3 == conc("1", Unit.MG, "1", Unit.ML).normalized().value


@given(
    amount=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("100000"), places=3),
)
def test_mass_units_are_consistent_for_any_amount(amount: Decimal) -> None:
    as_mg = Strength(Quantity(amount * 1000, Unit.MG)).normalized()
    as_g = Strength(Quantity(amount, Unit.G)).normalized()
    as_mcg = Strength(Quantity(amount * 1_000_000, Unit.MCG)).normalized()

    assert as_mg == as_g == as_mcg


@given(
    amount=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("100000"), places=3),
    per=st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1000"), places=3),
)
def test_concentration_is_invariant_under_unit_scaling(amount: Decimal, per: Decimal) -> None:
    in_mg_ml = Strength(Quantity(amount, Unit.MG), per=Quantity(per, Unit.ML)).normalized()
    in_g_l = Strength(
        Quantity(amount / 1000, Unit.G), per=Quantity(per / 1000, Unit.L)
    ).normalized()

    assert in_mg_ml == in_g_l


@pytest.mark.parametrize("bad", ["0", "-1", "NaN", "Infinity"])
def test_quantity_rejects_non_positive_and_non_finite_amounts(bad: str) -> None:
    with pytest.raises(InvariantViolation):
        Quantity(Decimal(bad), Unit.MG)


def test_quantity_rejects_float_amounts() -> None:
    with pytest.raises(InvariantViolation):
        Quantity(5.0, Unit.MG)  # type: ignore[arg-type]


@pytest.mark.parametrize("unit", [Unit.ML, Unit.L])
def test_numerator_must_be_mass_or_international_unit(unit: Unit) -> None:
    with pytest.raises(InvariantViolation):
        Strength(q("5", unit))


@pytest.mark.parametrize("unit", [Unit.MG, Unit.G, Unit.MCG, Unit.IU])
def test_denominator_must_be_a_volume(unit: Unit) -> None:
    with pytest.raises(InvariantViolation):
        Strength(q("5", Unit.MG), per=q("1", unit))
