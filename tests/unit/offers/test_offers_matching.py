from decimal import Decimal

from pharmavique.offers.domain.forms import dosage_form_key
from pharmavique.offers.domain.matching import PackSize, ProductFacts, assess, decide
from pharmavique.offers.domain.model import ListingCategory, MatchStatus
from pharmavique.offers.domain.quantity import Strength


def mg(value: str) -> Strength:
    return Strength("mass", Decimal(value))


FOUR = PackSize(count=4)


def facts(
    brand: str | None = "viagra",
    ingredients: tuple[str, ...] = ("sildenafil",),
    strengths: tuple[Strength, ...] = (mg("50"),),
    form: str | None = "tablet",
    pack: PackSize | None = FOUR,
    contradicts_itself: bool = False,
) -> ProductFacts:
    return ProductFacts(
        brand,
        frozenset(ingredients),
        frozenset(strengths),
        form,
        pack,
        contradicts_itself=contradicts_itself,
    )


REGISTRY = facts()


def test_every_field_equal_is_a_match() -> None:
    assert assess(facts(), REGISTRY).outcome == "matched"


def test_a_different_strength_of_the_same_brand_is_a_conflict_never_a_match() -> None:
    result = assess(facts(strengths=(mg("100"),)), REGISTRY)

    assert result.outcome == "conflict"
    assert result.conflict_reason == "strength"


def test_a_different_dosage_form_of_the_same_brand_is_a_conflict() -> None:
    result = assess(facts(form=dosage_form_key("Orodispersible tablet")), REGISTRY)

    assert result.outcome == "conflict"
    assert result.conflict_reason == "form"


def test_different_ingredients_under_the_same_brand_are_a_conflict() -> None:
    assert assess(facts(ingredients=("tadalafil",)), REGISTRY).conflict_reason == "ingredients"


def test_half_a_gram_equals_five_hundred_milligrams() -> None:
    registry = facts(strengths=(mg("500"),))
    listing = facts(strengths=(Strength("mass", Decimal("0.5") * 1000),))

    assert assess(listing, registry).outcome == "matched"


def test_a_missing_strength_on_the_listing_can_never_be_a_match() -> None:
    result = assess(facts(strengths=()), REGISTRY)

    assert result.outcome == "possible"
    assert result.verdicts["strength"] == "unknown"


def test_a_missing_form_or_pack_can_never_be_a_match() -> None:
    assert assess(facts(form=None), REGISTRY).outcome == "possible"
    assert assess(facts(pack=None), REGISTRY).outcome == "possible"


def test_a_different_pack_size_is_possible_not_matched_and_not_a_conflict() -> None:
    result = assess(facts(pack=PackSize(count=8)), REGISTRY)

    assert result.outcome == "possible"
    assert result.verdicts["pack"] == "different"


def test_another_brand_is_a_different_product_even_with_the_same_ingredient() -> None:
    assert assess(facts(brand="vega"), REGISTRY).outcome == "different_product"


def test_a_listing_without_a_brand_is_at_best_possible() -> None:
    assert assess(facts(brand=None), REGISTRY).outcome == "possible"
    assert assess(facts(brand=None, strengths=(mg("100"),)), REGISTRY).outcome == "conflict"


def test_a_cosmetic_or_device_is_never_compared_with_the_registry() -> None:
    for category in (ListingCategory.COSMETIC, ListingCategory.DEVICE, ListingCategory.OTHER):
        decision = decide(category, facts(), [("1", REGISTRY)])
        assert decision.status is MatchStatus.NOT_APPLICABLE
        assert decision.register_number is None


def test_an_unclassified_listing_is_never_compared_either() -> None:
    decision = decide(ListingCategory.UNCLASSIFIED, facts(), [("1", REGISTRY)])

    assert decision.status is MatchStatus.NOT_APPLICABLE


def test_one_matching_candidate_is_matched_with_its_evidence() -> None:
    decision = decide(ListingCategory.MEDICINE, facts(), [("1", REGISTRY)])

    assert decision.status is MatchStatus.MATCHED
    assert decision.register_number == "1"
    assert decision.evidence["verdicts"]["strength"] == "same"


def test_conflicting_candidates_are_recorded_and_never_chosen() -> None:
    other = facts(strengths=(mg("25"),))

    decision = decide(ListingCategory.MEDICINE, facts(), [("1", REGISTRY), ("2", other)])

    assert decision.status is MatchStatus.MATCHED
    assert decision.register_number == "1"
    assert decision.conflicts == (("2", "strength"),)


def test_only_a_conflicting_candidate_gives_no_match_and_a_conflict_record() -> None:
    decision = decide(ListingCategory.MEDICINE, facts(strengths=(mg("100"),)), [("1", REGISTRY)])

    assert decision.status is MatchStatus.NO_MATCH
    assert decision.register_number is None
    assert decision.conflicts == (("1", "strength"),)


def test_two_equally_good_candidates_need_review() -> None:
    decision = decide(ListingCategory.MEDICINE, facts(), [("1", REGISTRY), ("2", REGISTRY)])

    assert decision.status is MatchStatus.NEEDS_REVIEW
    assert decision.register_number is None


def test_a_listing_that_contradicts_itself_needs_review() -> None:
    decision = decide(ListingCategory.MEDICINE, facts(contradicts_itself=True), [("1", REGISTRY)])

    assert decision.status is MatchStatus.NEEDS_REVIEW


def test_one_possible_candidate_is_possible_and_several_need_review() -> None:
    unsure = facts(pack=None)

    assert (
        decide(ListingCategory.MEDICINE, unsure, [("1", REGISTRY)]).status is MatchStatus.POSSIBLE
    )
    assert (
        decide(ListingCategory.MEDICINE, unsure, [("1", REGISTRY), ("2", REGISTRY)]).status
        is MatchStatus.NEEDS_REVIEW
    )


def test_no_candidate_is_no_match() -> None:
    assert decide(ListingCategory.MEDICINE, facts(), []).status is MatchStatus.NO_MATCH


def test_dosage_form_keys_tell_forms_apart() -> None:
    assert dosage_form_key("Film-coated tablet") == "tablet"
    assert dosage_form_key("Orodispersible tablet") == "tablet:orodispersible"
    assert dosage_form_key("Prolonged-release tablet") == "tablet:modified"
    assert dosage_form_key("Solution for injection in pre-filled syringe") == "injection"
    assert dosage_form_key("Oral solution") == "solution"
    assert dosage_form_key("") is None
    assert dosage_form_key("something else") is None
