"""Look-alike sound-alike names: informational warnings computed from spelling and sound."""

import pytest

from pharmavique.search.domain.lasa import LasaIndex, phonetic_key


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("panadol", "panadole"),
        ("panadol", "banadol"),
        ("zyrtec", "zirtek"),
        ("بنادول", "بنادوول"),
        ("فولتارين", "فولطارين"),
    ],
)
def test_names_that_sound_the_same_share_a_key(a: str, b: str) -> None:
    assert phonetic_key(a) == phonetic_key(b)


@pytest.mark.parametrize(("a", "b"), [("panadol", "augmentin"), ("بنادول", "اوجمنتين")])
def test_different_names_have_different_keys(a: str, b: str) -> None:
    assert phonetic_key(a) != phonetic_key(b)


def index() -> LasaIndex:
    return LasaIndex(
        [
            ("1", "panadol"),
            ("2", "panadole"),
            ("3", "panadol extra"),
            ("4", "augmentin"),
            ("5", "banadol"),
            ("6", "panadol"),  # same brand, another strength: not a look-alike of itself
            ("7", "بنادول"),
            ("8", "بنادوول"),
        ]
    )


def test_a_name_that_differs_by_one_letter_is_found_as_a_look_alike() -> None:
    found = {m.register_number: m for m in index().similar_to("1", limit=10)}

    assert "2" in found
    assert found["2"].level == "high"
    assert "5" in found


def test_the_same_brand_or_its_extended_name_is_not_a_look_alike() -> None:
    found = {m.register_number for m in index().similar_to("1", limit=10)}

    assert "6" not in found  # same brand, another strength
    assert "3" not in found  # "panadol extra" is the same family as "panadol"


def test_an_unrelated_name_is_not_flagged() -> None:
    assert "4" not in {m.register_number for m in index().similar_to("1", limit=10)}


def test_arabic_names_are_compared_with_arabic_names() -> None:
    found = {m.register_number for m in index().similar_to("7", limit=10)}

    assert found == {"8"}


def test_results_are_best_first_and_limited() -> None:
    found = index().similar_to("1", limit=1)

    assert len(found) == 1
    assert found[0].register_number in {"2", "5"}


def test_an_unknown_register_number_has_no_look_alikes() -> None:
    assert index().similar_to("999", limit=10) == ()


def test_the_matches_of_every_product_at_once_equal_asking_one_by_one() -> None:
    # The daily refresh stores these; each brand is compared once and shared by its strengths.
    index = LasaIndex(
        [
            ("1", "panadol"),
            ("1b", "panadol"),  # another strength of the same brand
            ("2", "banadol"),
            ("3", "panadool"),
            ("4", "panadol extra"),
            ("5", "augmentin"),
            ("6", "بنادول"),
            ("7", "بنادوول"),
            ("8", ""),  # nothing left after normalizing: not indexed
        ]
    )

    every = index.similar_for_all(limit=2)

    assert set(every) == {"1", "1b", "2", "3", "4", "5", "6", "7"}
    for number, matches in every.items():
        assert matches == index.similar_to(number, 2), number
    assert every["1"]
    assert every["6"]
