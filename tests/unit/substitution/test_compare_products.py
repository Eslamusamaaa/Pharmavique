"""Comparing a product with others through the substitution rules (no LLM decides this)."""

from pharmavique.substitution.application.compare import CompareProductsHandler
from pharmavique.substitution.contracts.queries import IngredientFacts, ProductFacts


def product(pid: str, form: str | None, *lines: tuple[str, str | None, str | None]) -> ProductFacts:
    return ProductFacts(pid, tuple(IngredientFacts(*line) for line in lines), form)


BASE = product("base", "Tablet", ("PARACETAMOL", "500", "mg"))


def verdict_of(other: ProductFacts) -> str:
    (result,) = CompareProductsHandler().compare(BASE, [other])
    return result.verdict


def test_same_ingredient_strength_and_form_is_equivalent() -> None:
    assert verdict_of(product("x", "tablet", ("paracetamol", "500", "mg"))) == "equivalent"


def test_the_same_strength_in_another_unit_is_still_equivalent() -> None:
    assert verdict_of(product("x", "Tablet", ("PARACETAMOL", "0.5", "g"))) == "equivalent"


def test_a_different_strength_is_not_equivalent() -> None:
    assert verdict_of(product("x", "Tablet", ("PARACETAMOL", "650", "mg"))) == "not_equivalent"


def test_another_dosage_form_needs_a_pharmacist_check_not_a_guess() -> None:
    result = verdict_of(product("x", "Film-coated tablet", ("PARACETAMOL", "500", "mg")))

    assert result == "possible_needs_pharmacist_check"


def test_a_missing_or_unreadable_strength_needs_a_pharmacist_check() -> None:
    assert verdict_of(product("x", "Tablet", ("PARACETAMOL", None, None))) == (
        "possible_needs_pharmacist_check"
    )
    assert verdict_of(product("x", "Tablet", ("PARACETAMOL", "5", "%"))) == (
        "possible_needs_pharmacist_check"
    )


def test_a_concentration_compares_after_normalization() -> None:
    syrup = product("s", "Syrup", ("PARACETAMOL", "120", "mg/5ml"))
    same = product("t", "Syrup", ("PARACETAMOL", "24", "mg/ml"))

    (result,) = CompareProductsHandler().compare(syrup, [same])

    assert result.verdict == "equivalent"


def test_another_ingredient_set_is_not_equivalent() -> None:
    other = product("x", "Tablet", ("PARACETAMOL", "500", "mg"), ("CAFFEINE", "65", "mg"))

    assert verdict_of(other) == "not_equivalent"


def test_each_result_names_its_product_and_findings() -> None:
    (result,) = CompareProductsHandler().compare(
        BASE, [product("x", "Tablet", ("PARACETAMOL", "500", "mg"))]
    )

    assert result.product_id == "x"
    assert (result.ingredients, result.strength, result.form_family) == ("same", "same", "same")
