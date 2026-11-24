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


def full(pid: str, name: str, route: str | None, form: str = "Tablet") -> ProductFacts:
    return ProductFacts(pid, (IngredientFacts("PARACETAMOL", "500", "mg"),), form, route, name)


def test_the_same_drug_for_another_route_needs_a_pharmacist_check() -> None:
    # MESPORIN 1000 I.V and MESPORIN 1000 I.M. (that vial comes with a lidocaine solvent)
    base = full("1", "MESPORIN 1000 I.V", "Intravenous use", "Powder for solution for injection")
    other = full(
        "2", "MESPORIN 1000 I.M.", "Intramuscular use", "Powder for solution for injection"
    )
    same = full("3", "CEFTRI 1000", "Intravenous use", "Powder for solution for injection")

    results = CompareProductsHandler().compare(base, [other, same])

    assert [r.verdict for r in results] == ["possible_needs_pharmacist_check", "equivalent"]


def test_a_name_that_says_another_release_or_form_needs_a_pharmacist_check() -> None:
    # the registry writes "Tablet" for both, but one name says soluble, one says enteric coated
    base = full("1", "PANADREX 500 MG TAB", "Oral use")
    soluble = full("2", "PANADOL SOLUBLE 500MG TAB", "Oral use")
    coated = full("3", "RAZON 40 MG E.C TAB", "Oral use")
    plain = full("4", "OMOL 500MG TABLET", "Oral use")

    results = CompareProductsHandler().compare(base, [soluble, coated, plain])

    assert [r.verdict for r in results] == [
        "possible_needs_pharmacist_check",
        "possible_needs_pharmacist_check",
        "equivalent",
    ]


def combo(pid: str, name: str, ingredients: tuple[tuple[str, str], ...]) -> ProductFacts:
    lines = tuple(IngredientFacts(n, s, "mg") for n, s in ingredients)
    return ProductFacts(pid, lines, "Tablet", "Oral use", name)


def test_a_name_whose_printed_strength_disagrees_with_the_registry_needs_a_check() -> None:
    # Real SFDA rows: GARDIA PLUS 8/12.5 is recorded with candesartan 16 mg
    lines = (("CANDESARTAN CILEXETIL", "16"), ("HYDROCHLOROTHIAZIDE", "12.5"))
    base = combo("1", "CANDEZA 16/12.5 mg TABLETS", lines)
    wrong = combo("2", "GARDIA PLUS 8/12.5MG TABLETS", lines)
    right = combo("3", "GARDIA PLUS 16/12.5MG TABLETS", lines)
    grams = combo("4", "CANDESAR 0.016 G/12.5 MG", lines)

    results = CompareProductsHandler().compare(base, [wrong, right, grams])

    assert [r.verdict for r in results] == [
        "possible_needs_pharmacist_check",
        "equivalent",
        "equivalent",
    ]


def test_biosimilar_biologics_and_another_device_need_a_pharmacist_check() -> None:
    def bio(pid: str, name: str, ingredient: str) -> ProductFacts:
        line = (IngredientFacts(ingredient, "100", "iu/ml"),)
        return ProductFacts(pid, line, "Solution for injection", "Subcutaneous use", name)

    glargine = CompareProductsHandler().compare(
        bio("1", "LANTUS SOLOSTAR", "INSULIN GLARGINE"),
        [bio("2", "BASALOG ONE", "INSULIN GLARGINE")],
    )
    adalimumab = CompareProductsHandler().compare(
        bio("1", "Amgevita", "ADALIMUMAB"), [bio("2", "Hyrimoz", "ADALIMUMAB")]
    )

    assert glargine[0].verdict == "possible_needs_pharmacist_check"
    assert adalimumab[0].verdict == "possible_needs_pharmacist_check"


def test_a_name_that_prints_the_total_of_a_combination_agrees_with_the_registry() -> None:
    lines = (("AMOXICILLIN", "875"), ("CLAVULANIC ACID", "125"))
    base = combo("1", "AUGMENTIN 1 G TAB", lines)
    other = combo("2", "MEGAMOX 1GM TAB", lines)

    assert CompareProductsHandler().compare(base, [other])[0].verdict == "equivalent"
