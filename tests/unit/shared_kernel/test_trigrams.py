"""A pure-Python copy of how pg_trgm measures similarity, so ranking can be tested and tuned
without a database. Normalized text goes in; the numbers must agree with spike 001."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pharmavique.shared_kernel.trigrams import similarity, trigrams


def test_words_are_padded_like_pg_trgm() -> None:
    # pg_trgm pads each word with two spaces before and one after
    assert trigrams("cat") == frozenset({"  c", " ca", "cat", "at "})


def test_each_word_gets_its_own_trigrams_and_the_set_is_shared() -> None:
    assert trigrams("a b") == frozenset({"  a", " a ", "  b", " b "})


def test_nothing_gives_no_trigrams() -> None:
    assert trigrams("") == frozenset()
    assert trigrams("   ") == frozenset()


def test_identical_text_scores_one_and_unrelated_text_scores_zero() -> None:
    assert similarity("panadol", "panadol") == 1.0
    assert similarity("panadol", "xyz") == 0.0
    assert similarity("", "panadol") == 0.0


def test_a_misspelling_scores_between_zero_and_one_like_the_spike() -> None:
    # spike 001 measured 0.70 for panadol / panadool on pg_trgm
    assert similarity("panadol", "panadool") == pytest.approx(0.7, abs=0.01)
    assert similarity("بنادول", "بانادول") == pytest.approx(0.5, abs=0.01)


@given(st.text(alphabet="abc d", max_size=12), st.text(alphabet="abc d", max_size=12))
def test_similarity_is_symmetric_and_between_zero_and_one(a: str, b: str) -> None:
    assert similarity(a, b) == similarity(b, a)
    assert 0.0 <= similarity(a, b) <= 1.0
