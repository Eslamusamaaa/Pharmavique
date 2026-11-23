from decimal import Decimal

import pytest

from pharmavique.offers.domain.quantity import Strength, parse_strengths


def test_milligrams_are_the_base_unit() -> None:
    assert parse_strengths("Panadol 500 mg tablets") == (Strength("mass", Decimal("500")),)


def test_grams_and_micrograms_are_converted_to_milligrams() -> None:
    assert parse_strengths("0.5 g")[0] == parse_strengths("500 mg")[0]
    assert parse_strengths("250 mcg")[0] == Strength("mass", Decimal("0.25"))
    assert parse_strengths("250 µg")[0] == parse_strengths("250 mcg")[0]


def test_international_units_and_percent_are_their_own_kinds() -> None:
    assert parse_strengths("1000 IU") == (Strength("iu", Decimal("1000")),)
    assert parse_strengths("Cream 0.05%") == (Strength("percent", Decimal("0.05")),)
    assert parse_strengths("500 mg")[0] != parse_strengths("500 IU")[0]


def test_a_concentration_is_compared_as_an_amount_per_millilitre() -> None:
    assert parse_strengths("5 mg/5 ml") == parse_strengths("1 mg/ml")
    assert parse_strengths("5 mg/5 ml")[0] == Strength("mass_per_ml", Decimal("1"))
    assert parse_strengths("100 mg/ml")[0] != parse_strengths("100 mg")[0]


def test_a_combination_gives_one_strength_per_ingredient() -> None:
    found = parse_strengths("Co-Diovan 160 mg/12.5 mg")

    assert set(found) == {Strength("mass", Decimal("160")), Strength("mass", Decimal("12.5"))}


def test_arabic_indic_digits_and_a_decimal_comma_are_read() -> None:
    assert parse_strengths("٥٠٠ ملجم")[0] == Strength("mass", Decimal("500"))  # noqa: RUF001
    assert parse_strengths("0,5 g")[0] == Strength("mass", Decimal("500"))


@pytest.mark.parametrize("text", ["", "Panadol tablets", "30 tablets", "pack of 2"])
def test_text_without_a_strength_gives_none(text: str) -> None:
    assert parse_strengths(text) == ()
