"""Simple mapping of a web image to a drug, from the text around the image (title, alt, URL).

This is deliberately modest: it says "the page around this picture names this drug and shows signs
of being Saudi", not "the pixels are this exact pack". A stronger check (reading the box text with
OCR) can replace it later behind the same verdicts.
"""

from pharmavique.media.domain.matching import (
    ImageCandidate,
    MatchVerdict,
    ProductRef,
    build_queries,
    judge,
)
from pharmavique.shared_kernel.market import Market


def product(**overrides: object) -> ProductRef:
    fields: dict[str, object] = {
        "market": Market.SA,
        "register_number": "1-111-22",
        "trade_name_en": "PANADOL Extra",
        "trade_name_ar": "بنادول اكسترا",
        "ingredient_names": ("PARACETAMOL", "CAFFEINE"),
        "marketing_company": "GlaxoSmithKline",
    }
    fields.update(overrides)
    return ProductRef(**fields)  # type: ignore[arg-type]


def candidate(
    title: str = "",
    alt_text: str = "",
    page_url: str = "https://example.com/p",
    image_url: str = "https://example.com/i.jpg",
) -> ImageCandidate:
    return ImageCandidate(image_url=image_url, page_url=page_url, title=title, alt_text=alt_text)


def test_name_plus_saudi_evidence_is_a_match() -> None:
    result = judge(product(), candidate(title="Panadol Extra tablets - Saudi Arabia"))

    assert result.verdict is MatchVerdict.MATCHED
    assert {"name", "saudi"} <= set(result.signals)


def test_a_saudi_domain_counts_as_saudi_evidence() -> None:
    result = judge(
        product(), candidate(alt_text="Panadol Extra", page_url="https://pharmacy-example.com.sa/x")
    )

    assert result.verdict is MatchVerdict.MATCHED


def test_the_arabic_name_with_the_word_saudi_in_arabic_matches() -> None:
    result = judge(product(), candidate(title="بنادول اكسترا ٥٠٠ - السعودية"))

    assert result.verdict is MatchVerdict.MATCHED


def test_the_marketing_company_can_stand_in_for_saudi_evidence() -> None:
    result = judge(product(), candidate(title="Panadol Extra by GlaxoSmithKline"))

    assert result.verdict is MatchVerdict.MATCHED
    assert "company" in result.signals


def test_name_without_any_saudi_evidence_needs_a_person_to_look() -> None:
    # the same brand name is sold in other countries as a different product
    result = judge(product(), candidate(title="Panadol Extra 500mg caplets"))

    assert result.verdict is MatchVerdict.NEEDS_REVIEW


def test_a_page_that_does_not_name_the_drug_is_rejected_even_if_it_says_saudi() -> None:
    result = judge(product(), candidate(title="Paracetamol tablets Saudi Arabia pharmacy"))

    assert result.verdict is MatchVerdict.REJECTED
    assert "name" not in result.signals


def test_every_word_of_the_name_must_appear_not_just_one() -> None:
    result = judge(product(), candidate(title="Panadol Saudi Arabia"))

    assert result.verdict is MatchVerdict.REJECTED


def test_matching_ignores_case_diacritics_and_punctuation() -> None:
    result = judge(product(), candidate(title="PANADOL-EXTRA | saudi arabia"))

    assert result.verdict is MatchVerdict.MATCHED


def test_the_score_grows_with_the_evidence() -> None:
    weak = judge(product(), candidate(title="Panadol Extra"))
    strong = judge(
        product(), candidate(title="Panadol Extra paracetamol GlaxoSmithKline Saudi Arabia")
    )

    assert 0.0 <= weak.score < strong.score <= 1.0


def test_queries_name_the_drug_and_saudi_arabia_in_english_and_arabic() -> None:
    queries = build_queries(product())

    assert "PANADOL Extra PARACETAMOL Saudi Arabia" in queries
    assert any("بنادول اكسترا" in q and "السعودية" in q for q in queries)
    assert len(queries) == len(set(queries))


def test_queries_skip_a_missing_name_instead_of_searching_for_nothing() -> None:
    assert build_queries(product(trade_name_en=None, trade_name_ar=None)) == ()
    assert all("None" not in q for q in build_queries(product(trade_name_ar=None)))


def test_the_name_in_the_page_address_counts_when_the_title_is_generic() -> None:
    # seen on a real Saudi shop page: the title said "Product Overview", the address named the drug
    result = judge(
        product(),
        candidate(
            title="Product Overview",
            page_url="https://medononline.com.sa/product/panadol-extra-paracetamol-caffeine-24s-5179",
        ),
    )

    assert result.verdict is MatchVerdict.MATCHED
    assert "name" in result.signals


def test_the_website_name_alone_is_not_taken_as_the_drug_name() -> None:
    result = judge(product(), candidate(title="Welcome", page_url="https://panadol-extra.com.sa/"))

    assert result.verdict is MatchVerdict.REJECTED


def strong(**overrides: object) -> ProductRef:
    return product(strengths=("500 mg", "65 mg"), **overrides)


def with_text(text: str, title: str = "Panadol Extra Saudi Arabia") -> ImageCandidate:
    return ImageCandidate(
        image_url="https://example.com/i.jpg",
        page_url="https://example.com/p",
        title=title,
        alt_text="",
        page_text=text,
    )


def test_the_strength_from_the_registry_found_on_the_page_strengthens_the_match() -> None:
    result = judge(strong(), with_text("Each tablet contains Paracetamol 500mg and Caffeine 65mg"))

    assert result.verdict is MatchVerdict.MATCHED
    assert "strength" in result.signals


def test_a_page_that_states_only_other_strengths_goes_to_a_person() -> None:
    # same brand name, different strength: not the product in our registry
    result = judge(strong(), with_text("Panadol Extra 1000 mg tablets"))

    assert result.verdict is MatchVerdict.NEEDS_REVIEW
    assert "strength_conflict" in result.signals


def test_a_page_with_no_strength_at_all_is_neutral_about_it() -> None:
    result = judge(strong(), with_text("Fast relief for headaches"))

    assert result.verdict is MatchVerdict.MATCHED
    assert "strength" not in result.signals
    assert "strength_conflict" not in result.signals


def test_a_registry_product_without_strengths_never_conflicts() -> None:
    result = judge(product(), with_text("Panadol Extra 1000 mg tablets"))

    assert result.verdict is MatchVerdict.MATCHED
