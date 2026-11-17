from decimal import Decimal

import pytest

from pharmavique.catalog.domain.values import (
    LEGAL_STATUS,
    AtcCode,
    CodedValue,
    IngredientLine,
    LocalizedText,
    Package,
    Party,
    ProductId,
)
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.market import Market


def test_product_id_trims_the_register_number() -> None:
    assert ProductId(Market.SA, " 1-585-09 ").register_number == "1-585-09"


def test_product_id_rejects_a_blank_register_number() -> None:
    with pytest.raises(InvariantViolation):
        ProductId(Market.SA, "  ")


def test_product_ids_with_the_same_number_in_different_markets_differ() -> None:
    assert ProductId(Market.SA, "1") != ProductId(Market.EG, "1")


def test_localized_text_needs_at_least_one_language() -> None:
    with pytest.raises(InvariantViolation):
        LocalizedText(en=None, ar=None)
    with pytest.raises(InvariantViolation):
        LocalizedText(en="  ", ar="")


def test_localized_text_trims_and_turns_blank_into_none() -> None:
    text = LocalizedText(en="  Tablet ", ar="   ")

    assert text.en == "Tablet"
    assert text.ar is None


def test_ingredient_line_requires_a_name() -> None:
    with pytest.raises(InvariantViolation):
        IngredientLine(name=" ")


def test_ingredient_line_strength_is_optional_but_never_zero_or_negative() -> None:
    assert IngredientLine("PREDNISOLONE").strength is None
    assert IngredientLine("PREDNISOLONE", Decimal("1"), "%").strength == Decimal("1")
    for bad in (Decimal("0"), Decimal("-1"), Decimal("NaN")):
        with pytest.raises(InvariantViolation):
            IngredientLine("X", bad, "mg")


def test_ingredient_strength_must_be_a_decimal_not_a_float() -> None:
    with pytest.raises(InvariantViolation):
        IngredientLine("X", 5.0, "mg")  # type: ignore[arg-type]


def test_package_numbers_must_be_positive_when_present() -> None:
    assert Package().size is None
    with pytest.raises(InvariantViolation):
        Package(size=Decimal("0"))
    with pytest.raises(InvariantViolation):
        Package(package_size=0)


def test_coded_value_keeps_the_raw_text_and_recognises_known_values() -> None:
    value = CodedValue.of(" Prescription ", LEGAL_STATUS)

    assert value.raw == "Prescription"
    assert value.kind == "prescription"


def test_coded_value_recognition_ignores_case() -> None:
    assert CodedValue.of("OTC", LEGAL_STATUS).kind == "otc"
    assert CodedValue.of("otc", LEGAL_STATUS).kind == "otc"


def test_coded_value_keeps_unknown_values_instead_of_guessing() -> None:
    value = CodedValue.of("Special access", LEGAL_STATUS)

    assert value.raw == "Special access"
    assert value.kind is None


def test_coded_value_rejects_blank_text() -> None:
    with pytest.raises(InvariantViolation):
        CodedValue.of("  ", LEGAL_STATUS)


@pytest.mark.parametrize("code", ["S01BA04", "A07CA", "A", "A07", "A07C"])
def test_valid_atc_codes(code: str) -> None:
    assert AtcCode(code).code == code


@pytest.mark.parametrize("code", ["s01ba04", "S01BA0", "123", "S1", "", "S01BA04X"])
def test_invalid_atc_codes(code: str) -> None:
    with pytest.raises(InvariantViolation):
        AtcCode(code)


def test_party_needs_a_name_and_country_is_optional() -> None:
    assert Party("Maker A").country is None
    assert Party("Maker A", " Turkey ").country == "Turkey"
    assert Party("Maker A", "  ").country is None
    with pytest.raises(InvariantViolation):
        Party("  ")
