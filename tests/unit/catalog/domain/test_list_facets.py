"""Clean filter values for list rows: the site spells the same thing several ways."""

import pytest

from pharmavique.catalog.domain.list_facets import facets_for


def approval(**cells: str) -> dict[str, str]:
    base = {
        "Request Type": "New Registration",
        "Drug Type": "Generic Drug",
        "Dosage Form": "Film-coated tablet",
    }
    return facets_for(
        "drug-approvals", {**base, **{k.replace("_", " "): v for k, v in cells.items()}}
    )


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Generic(Multisource) Drug", "generic"),
        ("Generic (Multisource) Drug", "generic"),
        ("Generic", "generic"),
        ("Generic Drug", "generic"),
        ("New Drug", "new_drug"),
        ("NCE", "nce"),
        ("Biological Drug", "biological"),
        ("Biological", "biological"),
        ("Biosimilar", "biosimilar"),
    ],
)
def test_the_spellings_of_a_drug_type_collapse_to_one_value(raw: str, clean: str) -> None:
    assert approval(Drug_Type=raw)["drug_type"] == clean


def test_an_unknown_drug_type_is_kept_as_a_slug_not_guessed() -> None:
    assert approval(Drug_Type="Orphan Drug")["drug_type"] == "orphan_drug"


def test_request_type_and_dosage_form_are_cleaned() -> None:
    result = approval(Request_Type="Registration", Dosage_Form="Film-Coated tablet")
    assert result["request_type"] == "registration"
    assert result["dosage_form"] == "film-coated tablet"


def test_a_row_the_site_shifted_by_a_column_is_flagged_not_repaired() -> None:
    result = approval(
        Request_Type="Powder and solvent for solution for injection",
        Dosage_Form="-",
    )
    assert result["row_shifted"] == "true"
    assert "request_type" not in result
    assert "dosage_form" not in result


def test_a_missing_request_type_is_simply_absent() -> None:
    assert "request_type" not in approval(Request_Type="")


def test_company_status_and_type_are_translated() -> None:
    result = facets_for(
        "drug-companies", {"Company status": "مسجلة", "Drug Type": "بشرية", "Country Desc": "الهند"}
    )
    assert result == {"status": "registered", "drug_type": "human"}
    assert facets_for("drug-companies", {"Company status": "معلقة"})["status"] == "suspended"
    assert facets_for("drug-companies", {"Company status": "ملغية"})["status"] == "cancelled"


def test_shortage_lists_say_whether_the_shortage_is_open_or_resolved() -> None:
    assert facets_for("drug-shortage", {"Availability Status": "غير متوفر"}) == {
        "availability": "unavailable"
    }
    assert facets_for("drug-shortage-resolved", {"Availability Status": "تم الحل"}) == {
        "availability": "resolved"
    }


def test_other_lists_have_no_facets() -> None:
    assert facets_for("pharmacies", {"Region": "Riyadh"}) == {}
