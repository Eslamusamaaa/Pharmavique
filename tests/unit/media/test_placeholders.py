"""When no real picture of a drug exists on the web, the mapping says so and offers a picture of
its dosage form instead, clearly marked as a placeholder (never passed off as the drug's box)."""

import pytest

from pharmavique.media.domain.placeholders import FORMS, form_group, placeholder_svg


@pytest.mark.parametrize(
    ("dosage_form", "group"),
    [
        ("Tablet", "tablet"),
        ("Film-coated tablet", "tablet"),
        ("Prolonged-release tablet", "tablet"),
        ("Chewable tablet", "tablet"),
        ("Capsule, hard", "capsule"),
        ("Gastro-resistant capsule", "capsule"),
        ("Syrup", "liquid"),
        ("Powder for oral suspension", "liquid"),
        ("Oral solution", "liquid"),
        ("Eye drops, solution", "drops"),
        ("Solution for injection", "injection"),
        ("Powder for solution for injection/infusion", "injection"),
        ("Concentrate for solution for infusion", "injection"),
        ("Solution for haemodialysis", "injection"),
        ("Cream", "topical"),
        ("Ointment", "topical"),
        ("Gel", "topical"),
        ("Transdermal patch", "topical"),
        ("Inhalation powder", "inhaler"),
        ("Nasal spray", "inhaler"),
        ("Pressurised inhalation, solution", "inhaler"),
        ("Suppository", "suppository"),
        ("Vaginal delivery system", "suppository"),
        ("", "other"),
        (None, "other"),
        ("Something unheard of", "other"),
    ],
)
def test_a_dosage_form_falls_into_one_picture_group(dosage_form: str | None, group: str) -> None:
    assert form_group(dosage_form) == group


def test_every_group_has_a_picture_and_it_is_a_valid_small_vector_image() -> None:
    assert set(FORMS) == {
        "tablet", "capsule", "liquid", "drops", "injection", "topical", "inhaler",
        "suppository", "other",
    }  # fmt: skip
    for group in FORMS:
        svg = placeholder_svg(group)
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")
        assert len(svg) < 4000
        assert "<script" not in svg


def test_a_drug_card_shows_the_names_and_strength_and_says_it_is_not_the_real_pack() -> None:
    from xml.etree import ElementTree

    from pharmavique.media.domain.placeholders import drug_card_svg

    svg = drug_card_svg(
        group="capsule",
        name_en="AMLOR <5> & CO",
        name_ar="املور",
        strength="5 mg",
        form="Capsule",
        company="Pfizer",
    )
    root = ElementTree.fromstring(svg)  # noqa: S314  (our own output; checks well-formedness)
    text = " ".join(root.itertext())
    assert "AMLOR <5> & CO" in text
    assert "املور" in text
    assert "5 mg" in text
    assert "Pfizer" in text
    assert "not a photo" in text.lower()


def test_a_very_long_name_is_shortened_so_it_stays_inside_the_card() -> None:
    from pharmavique.media.domain.placeholders import drug_card_svg

    svg = drug_card_svg(
        group="other", name_en="X" * 200, name_ar="", strength="", form="", company=""
    )
    assert "X" * 60 not in svg
