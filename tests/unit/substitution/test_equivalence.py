from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.substitution.domain.equivalence import Match, assess
from pharmavique.substitution.domain.spec import (
    DosageFormFamily,
    IngredientStrength,
    ProductSpec,
)
from pharmavique.substitution.domain.strength import Quantity, Strength, Unit

# All names, ids and families below are synthetic test fixtures, not catalog data.
ORAL = DosageFormFamily("family-a")
TOPICAL = DosageFormFamily("family-b")


def mg(amount: str) -> Strength:
    return Strength(Quantity(Decimal(amount), Unit.MG))


def ing(ingredient_id: str | None, strength: Strength | None) -> IngredientStrength:
    return IngredientStrength(ingredient_id, strength)


def spec(
    *ingredients: IngredientStrength, family: DosageFormFamily | None = ORAL, pid: str = "p"
) -> ProductSpec:
    return ProductSpec(pid, tuple(ingredients), family)


def test_identical_single_ingredient_products_are_equivalent() -> None:
    result = assess(spec(ing("x", mg("500"))), spec(ing("x", mg("500"))))

    assert result.verdict is Match.EQUIVALENT


def test_strength_is_compared_after_unit_normalization() -> None:
    grams = Strength(Quantity(Decimal("0.5"), Unit.G))

    assert assess(spec(ing("x", mg("500"))), spec(ing("x", grams))).verdict is Match.EQUIVALENT


def test_different_strength_is_not_equivalent() -> None:
    assert (
        assess(spec(ing("x", mg("500"))), spec(ing("x", mg("250")))).verdict is Match.NOT_EQUIVALENT
    )


def test_different_ingredient_is_not_equivalent() -> None:
    assert (
        assess(spec(ing("x", mg("500"))), spec(ing("y", mg("500")))).verdict is Match.NOT_EQUIVALENT
    )


def test_different_form_family_is_not_equivalent() -> None:
    result = assess(spec(ing("x", mg("5")), family=ORAL), spec(ing("x", mg("5")), family=TOPICAL))

    assert result.verdict is Match.NOT_EQUIVALENT


def test_combination_products_match_regardless_of_ingredient_order() -> None:
    a = spec(ing("x", mg("500")), ing("y", mg("30")))
    b = spec(ing("y", mg("30")), ing("x", mg("500")))

    assert assess(a, b).verdict is Match.EQUIVALENT


def test_combination_with_one_different_strength_is_not_equivalent() -> None:
    a = spec(ing("x", mg("500")), ing("y", mg("30")))
    b = spec(ing("x", mg("500")), ing("y", mg("60")))

    assert assess(a, b).verdict is Match.NOT_EQUIVALENT


def test_combination_is_not_equivalent_to_its_single_ingredient_subset() -> None:
    combo = spec(ing("x", mg("500")), ing("y", mg("30")))
    single = spec(ing("x", mg("500")))

    assert assess(combo, single).verdict is Match.NOT_EQUIVALENT


def test_unknown_strength_is_possible_not_equivalent() -> None:
    result = assess(spec(ing("x", None)), spec(ing("x", mg("500"))))

    assert result.verdict is Match.POSSIBLE_NEEDS_PHARMACIST_CHECK


def test_unresolved_ingredient_is_possible_not_equivalent() -> None:
    result = assess(spec(ing(None, mg("500"))), spec(ing("x", mg("500"))))

    assert result.verdict is Match.POSSIBLE_NEEDS_PHARMACIST_CHECK


def test_unknown_form_family_is_possible_not_equivalent() -> None:
    result = assess(spec(ing("x", mg("5")), family=None), spec(ing("x", mg("5"))))

    assert result.verdict is Match.POSSIBLE_NEEDS_PHARMACIST_CHECK


def test_a_known_difference_wins_over_unknowns_elsewhere() -> None:
    a = spec(ing("x", None), family=ORAL)
    b = spec(ing("x", mg("5")), family=TOPICAL)

    assert assess(a, b).verdict is Match.NOT_EQUIVALENT


def test_ingredient_count_mismatch_is_definitely_not_equivalent_even_with_unresolved() -> None:
    a = spec(ing(None, None), ing("x", mg("5")))
    b = spec(ing("x", mg("5")))

    assert assess(a, b).verdict is Match.NOT_EQUIVALENT


def test_a_product_must_not_list_the_same_ingredient_twice() -> None:
    with pytest.raises(InvariantViolation):
        spec(ing("x", mg("5")), ing("x", mg("10")))


def test_a_product_needs_at_least_one_ingredient() -> None:
    with pytest.raises(InvariantViolation):
        ProductSpec("p", (), ORAL)


def test_family_code_must_not_be_blank() -> None:
    with pytest.raises(InvariantViolation):
        DosageFormFamily("  ")


def test_result_explains_each_dimension() -> None:
    result = assess(spec(ing("x", mg("500"))), spec(ing("x", mg("250"))))

    assert result.ingredients.value == "same"
    assert result.strength.value == "different"
    assert result.form_family.value == "same"


# ---- properties -----------------------------------------------------------------------------

ingredient_ids = st.sampled_from(["a", "b", "c", "d"])
strengths = st.one_of(
    st.none(),
    st.sampled_from(["1", "5", "250", "500"]).map(mg),
)
families = st.sampled_from([None, ORAL, TOPICAL])


@st.composite
def specs(draw: st.DrawFn) -> ProductSpec:
    ids = draw(st.lists(st.one_of(st.none(), ingredient_ids), min_size=1, max_size=3))
    seen: set[str] = set()
    items: list[IngredientStrength] = []
    for ingredient_id in ids:
        if ingredient_id is not None:
            if ingredient_id in seen:
                continue
            seen.add(ingredient_id)
        items.append(IngredientStrength(ingredient_id, draw(strengths)))
    return ProductSpec("p", tuple(items), draw(families))


@given(specs(), specs())
def test_assessment_is_symmetric(a: ProductSpec, b: ProductSpec) -> None:
    assert assess(a, b).verdict is assess(b, a).verdict


@given(specs(), specs())
def test_equivalent_only_when_everything_is_known_and_identical(
    a: ProductSpec, b: ProductSpec
) -> None:
    if assess(a, b).verdict is not Match.EQUIVALENT:
        return

    for product in (a, b):
        assert product.form_family is not None
        for item in product.ingredients:
            assert item.ingredient_id is not None
            assert item.strength is not None
    assert a.form_family == b.form_family
    left = {i.ingredient_id: i.strength.normalized() for i in a.ingredients if i.strength}
    right = {i.ingredient_id: i.strength.normalized() for i in b.ingredients if i.strength}
    assert left == right


@given(specs())
def test_a_fully_known_product_is_equivalent_to_itself(a: ProductSpec) -> None:
    fully_known = a.form_family is not None and all(
        i.ingredient_id is not None and i.strength is not None for i in a.ingredients
    )
    verdict = assess(a, a).verdict

    assert (verdict is Match.EQUIVALENT) == fully_known
