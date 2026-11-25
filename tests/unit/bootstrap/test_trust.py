"""Trust grades (owner's decision, 2026-11-25): three, so a screen never mixes official Saudi data,
an official foreign reference and unverified research data."""

import pytest

from pharmavique.bootstrap.trust import (
    GRADE_LABEL_AR,
    SOURCES,
    TrustGrade,
    grade_of_citation,
    grade_of_source,
    source_key_for_host,
)


@pytest.mark.parametrize(
    ("source", "grade"),
    [
        ("ddinter-2.0", TrustGrade.UNVERIFIED),
        ("DDInter 2.0", TrustGrade.UNVERIFIED),
        ("medic", TrustGrade.UNVERIFIED),
        ("MeDIC", TrustGrade.UNVERIFIED),
        ("openfda", TrustGrade.OFFICIAL_FOREIGN),
        ("sfda", TrustGrade.OFFICIAL_SA),
        ("sfda-drugs", TrustGrade.OFFICIAL_SA),
        # a source nobody listed is never promoted
        ("something-new", TrustGrade.UNVERIFIED),
        (None, TrustGrade.UNVERIFIED),
        ("", TrustGrade.UNVERIFIED),
    ],
)
def test_a_source_name_maps_to_its_grade(source: str | None, grade: TrustGrade) -> None:
    assert grade_of_source(source) is grade


@pytest.mark.parametrize(
    ("kind", "source_id", "url", "grade"),
    [
        ("catalog", "catalog:1234", None, TrustGrade.OFFICIAL_SA),
        (
            "sfda_site",
            "sfda_site:x",
            "https://www.sfda.gov.sa/en/drugs-list",
            TrustGrade.OFFICIAL_SA,
        ),
        ("interaction", "interaction:ddinter-2.0:a:b", None, TrustGrade.UNVERIFIED),
        ("contraindication", "contraindication:medic:x", None, TrustGrade.UNVERIFIED),
        ("web", "web:1", "https://example.com", TrustGrade.UNVERIFIED),
        ("document", "document:1", "https://www.sfda.gov.sa/ar/x.pdf", TrustGrade.OFFICIAL_SA),
        (
            "document",
            "document:2",
            "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=1",
            TrustGrade.OFFICIAL_FOREIGN,
        ),
        (
            "document",
            "document:3",
            "https://api.fda.gov/drug/label.json",
            TrustGrade.OFFICIAL_FOREIGN,
        ),
        ("document", "document:4", "https://evil-sfda.gov.sa.example.com/x", TrustGrade.UNVERIFIED),
        ("document", "document:5", None, TrustGrade.UNVERIFIED),
        ("whatever", "x", None, TrustGrade.UNVERIFIED),
    ],
)
def test_a_citation_gets_the_grade_of_what_it_cites(
    kind: str, source_id: str, url: str | None, grade: TrustGrade
) -> None:
    assert grade_of_citation(kind, source_id, url) is grade


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("www.sfda.gov.sa", "sfda-safety-documents"),
        ("sfda.gov.sa", "sfda-safety-documents"),
        ("dailymed.nlm.nih.gov", "openfda-labels"),
        ("api.fda.gov", "openfda-labels"),
        ("sfda.gov.sa.example.com", None),
        ("example.com", None),
        ("", None),
    ],
)
def test_a_document_host_maps_to_a_source(host: str, key: str | None) -> None:
    assert source_key_for_host(host) == key


def test_every_grade_has_an_arabic_label() -> None:
    assert set(GRADE_LABEL_AR) == set(TrustGrade)


def test_the_catalogue_names_each_source_once_with_a_grade() -> None:
    ids = [s.id for s in SOURCES]
    assert len(ids) == len(set(ids))
    by_id = {s.id: s for s in SOURCES}
    assert by_id["ddinter-2.0"].grade is TrustGrade.UNVERIFIED
    assert by_id["medic"].grade is TrustGrade.UNVERIFIED
    assert by_id["openfda-labels"].grade is TrustGrade.OFFICIAL_FOREIGN
    assert by_id["sfda-drugs"].grade is TrustGrade.OFFICIAL_SA
    assert by_id["product-pictures"].grade is TrustGrade.UNVERIFIED
