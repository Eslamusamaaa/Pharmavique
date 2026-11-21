"""Reading the drug-interactions section out of an openFDA label answer."""

from typing import Any

from pharmavique.knowledge.infrastructure.openfda import parse_label


def label(**fields: Any) -> dict[str, Any]:
    base = {
        "set_id": "0cbce382-9c88-4f58-ae0f-532a841e8f95",
        "effective_time": "20240112",
        "openfda": {"generic_name": ["WARFARIN SODIUM"]},
    }
    return base | fields


def test_the_interactions_text_is_joined_with_its_source_page_and_date() -> None:
    payload = {
        "results": [label(drug_interactions=["7 DRUG INTERACTIONS Bleeding risk.", "7.1 General."])]
    }

    found = parse_label(payload)

    assert found is not None
    assert found.generic_name == "WARFARIN SODIUM"
    assert found.text == "7 DRUG INTERACTIONS Bleeding risk.\n\n7.1 General."
    assert found.effective_time == "2024-01-12"
    assert found.source_ref == (
        "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=0cbce382-9c88-4f58-ae0f-532a841e8f95"
    )


def test_the_first_label_that_has_an_interactions_section_is_used() -> None:
    payload = {"results": [label(), label(set_id="b", drug_interactions=["Second label text."])]}

    found = parse_label(payload)

    assert found is not None
    assert found.text == "Second label text."


def test_no_results_or_no_interactions_section_gives_nothing() -> None:
    assert parse_label({"results": []}) is None
    assert parse_label({"results": [label()]}) is None
    assert parse_label({"error": {"code": "NOT_FOUND"}}) is None


def test_a_single_ingredient_wanted_skips_combination_labels() -> None:
    combo = label(
        set_id="combo",
        drug_interactions=["Combination text."],
        openfda={"generic_name": ["HYDROCODONE BITARTRATE AND ACETAMINOPHEN"]},
    )
    single = label(
        set_id="single",
        drug_interactions=["Single text."],
        openfda={"generic_name": ["ACETAMINOPHEN"]},
    )

    found = parse_label({"results": [combo, single]}, wanted="acetaminophen")

    assert found is not None
    assert found.set_id == "single"
    assert parse_label({"results": [combo]}, wanted="acetaminophen") is None


def test_a_salt_form_of_the_wanted_name_is_accepted() -> None:
    payload = {"results": [label(drug_interactions=["Text."])]}

    found = parse_label(payload, wanted="warfarin")

    assert found is not None
    assert found.generic_name == "WARFARIN SODIUM"


def test_the_other_label_sections_of_the_same_label_come_along_by_name() -> None:
    payload = {
        "results": [
            label(
                drug_interactions=["Interactions text."],
                contraindications=["Contraindicated in pregnancy."],
                pregnancy=["Pregnancy text."],
                lactation=["Lactation text."],
                information_for_patients=["Take with food."],
                dosage_and_administration=["Never kept: dosing."],
            )
        ]
    }

    found = parse_label(payload)

    assert found is not None
    assert dict(found.sections) == {
        "contraindications": "Contraindicated in pregnancy.",
        "pregnancy": "Pregnancy text.",
        "lactation": "Lactation text.",
        "information_for_patients": "Take with food.",
    }
