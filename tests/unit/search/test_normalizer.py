"""Normalization makes Arabic and Latin names comparable; one function for index and query."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pharmavique.search.domain.normalizer import normalize_text, tokenize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("بَانَادُول", "بانادول"),  # diacritics (spike 001: similarity was 0.118 without this)
        ("بانادول", "بانادول"),
        ("أموكسيسيلين", "اموكسيسيلين"),  # alef with hamza above
        ("إموكسيسيلين", "اموكسيسيلين"),  # alef with hamza below
        ("آموكسيسيلين", "اموكسيسيلين"),  # alef with madda
        ("اموكسيسيلين", "اموكسيسيلين"),
        ("بنادولى", "بنادولي"),  # alef maqsura to ya
        ("أسبرينة", "اسبرينه"),  # ta marbuta to ha
        ("بـــانادول", "بانادول"),  # tatweel
        ("مؤتمر", "موتمر"),  # waw with hamza
        ("شائع", "شايع"),  # ya with hamza
    ],
)
def test_arabic_variants_collapse_to_one_form(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_arabic_indic_and_persian_digits_become_ascii() -> None:
    assert normalize_text("بانادول ٥٠٠ مجم") == "بانادول 500 مجم"
    assert normalize_text("۵۰۰") == "500"


def test_latin_is_lowercased_and_accents_are_dropped() -> None:
    assert normalize_text("PANADOL Extra") == "panadol extra"
    assert normalize_text("Café") == "cafe"


def test_punctuation_becomes_spaces_but_decimals_survive() -> None:
    assert (
        normalize_text("Amoxicillin/Clavulanic-acid (500mg)")
        == "amoxicillin clavulanic acid 500 mg"
    )
    assert normalize_text("Vit. D3 0.5 mg") == "vit d 3 0.5 mg"
    assert normalize_text("٠٫٥ مجم") == "0.5 مجم"  # Arabic decimal separator


def test_arabic_punctuation_is_removed() -> None:
    assert normalize_text("بانادول، اكسترا؛ ٥٠٠") == "بانادول اكسترا 500"


def test_letters_and_digits_are_separated_which_helps_with_ocr_text() -> None:
    assert normalize_text("paracetamol500mg") == "paracetamol 500 mg"


def test_whitespace_is_collapsed_and_edges_trimmed() -> None:
    assert normalize_text("  a \t b\n\nc  ") == "a b c"


def test_empty_and_blank_text_give_the_empty_string() -> None:
    assert normalize_text("") == ""
    assert normalize_text("  ، / ") == ""


def test_misspelled_arabic_names_still_differ_but_share_tokens_after_normalizing() -> None:
    assert tokenize("بَنادول اكسترا") == ("بنادول", "اكسترا")
    assert tokenize("PANADOL  Extra") == ("panadol", "extra")


def test_arabic_and_latin_in_one_string_are_both_kept() -> None:
    assert normalize_text("Panadol بانادول") == "panadol بانادول"


@given(st.text(max_size=60))
def test_normalizing_twice_changes_nothing(text: str) -> None:
    once = normalize_text(text)
    assert normalize_text(once) == once


@given(st.text(max_size=60))
def test_output_has_no_leading_trailing_or_double_spaces(text: str) -> None:
    out = normalize_text(text)
    assert out == out.strip()
    assert "  " not in out
