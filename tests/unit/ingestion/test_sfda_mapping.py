"""The anti-corruption layer: SFDA's stored record to the catalog's `ProductSnapshot`.

Records are synthetic but shaped exactly like the stored ones (English and Arabic label/value
lists). Nothing here reads real data.
"""

from decimal import Decimal
from typing import Any

from pharmavique.catalog.application.translate import snapshot_to_data
from pharmavique.catalog.contracts.commands import IngredientLineDto, PartyDto
from pharmavique.ingestion.infrastructure.connectors.sfda_web.mapping import (
    REQUIRED_LABELS,
    check_required_labels,
    to_product_snapshot,
)
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money

SAR = Currency.owner_assumed("SAR")

EN: dict[str, str] = {
    "Register Number": "1-111-22",
    "Trade Name": "ACME-ONE 5MG TAB",
    "Scientific Name": "ACMEDRONE",
    "Strength": "5",
    "Strength Unit": "mg",
    "Dosage Form": "Tablet",
    "Route of Administration": "Oral use",
    "Size": "",
    "Size Unit": "",
    "Package Type": "Blister",
    "Package Size": "30",
    "Legal Status": "Prescription",
    "Product Control": "Uncontrolled",
    "Distribution Site": "Pharmacy",
    "Shelf Life": "24",
    "Storage Conditions": "store below 25c",
    "Manufacturers": "Name: Maker A | Country: Atlantis\nName: Maker B | Country: Mu",
    "Marketing Company": "Maker A",
    "Country of marketing company": "Atlantis",
    "Agents": "AGENT ONE\nAGENT TWO",
    "ATC Code 1": "A07CA",
    "ATC Code 2": "",
    "Description Code": "7000-1",
    "Authorization Status": "Valid",
    "Marketing Status": "Marketed",
    "Price": "9.5",
}

AR: dict[str, str] = {
    "رقم التسجيل": "1-111-22",
    "الاسم التجاري": "اكمي ون",
    "الشكل الصيدلاني": "اقراص",
    "طريقة الإستعمال": "استخدام فموي",
    "ظروف التخزين": "يحفظ تحت 25 درجة",
}


def rows(values: dict[str, str]) -> list[dict[str, str]]:
    return [{"label": label, "value": value} for label, value in values.items()]


def record(
    en: dict[str, str] | None = None, ar: dict[str, str] | str | None = "default"
) -> dict[str, Any]:
    merged = {**EN, **(en or {})}
    arabic: list[dict[str, str]] | None = rows(AR) if ar == "default" else None
    if isinstance(ar, dict):
        arabic = rows(ar)
    return {"key": "1-111-22", "list": {}, "en": rows(merged), "ar": arabic, "provenance": {}}


def mapped(en: dict[str, str] | None = None, **kwargs: Any) -> Any:
    result = to_product_snapshot(record(en, **kwargs), SAR)
    assert result is not None
    return result


def test_a_simple_record_maps_every_field() -> None:
    snapshot = mapped().snapshot

    assert snapshot.market is Market.SA
    assert snapshot.register_number == "1-111-22"
    assert (snapshot.trade_name_en, snapshot.trade_name_ar) == ("ACME-ONE 5MG TAB", "اكمي ون")
    assert snapshot.ingredients == (IngredientLineDto("ACMEDRONE", Decimal("5"), "mg"),)
    assert (snapshot.dosage_form_en, snapshot.dosage_form_ar) == ("Tablet", "اقراص")
    assert (snapshot.route_en, snapshot.route_ar) == ("Oral use", "استخدام فموي")
    assert snapshot.package_size is None
    assert (snapshot.package_type, snapshot.package_count) == ("Blister", 30)
    assert snapshot.legal_status == "Prescription"
    assert snapshot.product_control == "Uncontrolled"
    assert snapshot.distribution_site == "Pharmacy"
    assert snapshot.authorization_status == "Valid"
    assert snapshot.marketing_status == "Marketed"
    assert snapshot.atc_codes == ("A07CA",)
    assert snapshot.shelf_life == "24"
    assert (snapshot.storage_conditions_en, snapshot.storage_conditions_ar) == (
        "store below 25c",
        "يحفظ تحت 25 درجة",
    )
    assert snapshot.marketing_company == PartyDto("Maker A", "Atlantis")
    assert snapshot.agents == ("AGENT ONE", "AGENT TWO")
    assert snapshot.description_code == "7000-1"


def test_the_price_uses_the_currency_the_caller_decided() -> None:
    assert mapped().snapshot.price == Money(Decimal("9.5"), SAR)
    other = Currency.confirmed("USD")
    result = to_product_snapshot(record(), other)
    assert result is not None
    assert result.snapshot.price == Money(Decimal("9.5"), other)


def test_a_blank_price_is_none_and_garbage_is_none_with_an_issue() -> None:
    assert mapped({"Price": ""}).snapshot.price is None

    result = mapped({"Price": "free"})

    assert result.snapshot.price is None
    assert any("price" in issue for issue in result.issues)


def test_a_combination_product_pairs_each_name_with_its_strength() -> None:
    result = mapped(
        {
            "Scientific Name": "SODIUM CHLORIDE,POTASSIUM CHLORIDE,DEXTROSE",
            "Strength": "0.52,0.3,2.7",
            "Strength Unit": "g",
        }
    )

    assert result.snapshot.ingredients == (
        IngredientLineDto("SODIUM CHLORIDE", Decimal("0.52"), "g"),
        IngredientLineDto("POTASSIUM CHLORIDE", Decimal("0.3"), "g"),
        IngredientLineDto("DEXTROSE", Decimal("2.7"), "g"),
    )
    assert result.issues == ()


def test_when_names_and_strengths_do_not_line_up_nothing_is_paired_by_guess() -> None:
    result = mapped(
        {"Scientific Name": "2,4-DICHLOROBENZYL ALCOHOL", "Strength": "1.2", "Strength Unit": "mg"}
    )

    assert result.snapshot.ingredients == (IngredientLineDto("2,4-DICHLOROBENZYL ALCOHOL"),)
    assert any("ingredient" in issue for issue in result.issues)


def test_an_unreadable_strength_leaves_the_names_unpaired() -> None:
    result = mapped({"Scientific Name": "AAA,BBB", "Strength": "1:2,5", "Strength Unit": "mg"})

    assert result.snapshot.ingredients == (IngredientLineDto("AAA,BBB"),)
    assert result.issues


def test_a_missing_strength_keeps_the_names_without_strengths() -> None:
    result = mapped({"Scientific Name": "AAA", "Strength": "", "Strength Unit": ""})

    assert result.snapshot.ingredients == (IngredientLineDto("AAA"),)
    assert result.issues == ()


def test_manufacturer_lines_are_read_and_odd_lines_are_kept_as_names() -> None:
    result = mapped({"Manufacturers": "Name: Maker A | Country: Atlantis\nPlain Maker Ltd"})

    assert result.snapshot.manufacturers == (
        PartyDto("Maker A", "Atlantis"),
        PartyDto("Plain Maker Ltd"),
    )


def test_both_atc_codes_are_kept_and_blank_ones_dropped() -> None:
    assert mapped({"ATC Code 1": "A07CA", "ATC Code 2": "S01BA04"}).snapshot.atc_codes == (
        "A07CA",
        "S01BA04",
    )
    assert mapped({"ATC Code 1": "", "ATC Code 2": ""}).snapshot.atc_codes == ()


def test_an_atc_value_that_carries_its_description_gives_the_code_in_front() -> None:
    # seen live: "N02C-ANTIMIGRAINE PREPARATIONS" in the ATC field
    result = mapped({"ATC Code 1": "N02C-ANTIMIGRAINE PREPARATIONS", "ATC Code 2": ""})

    assert result.snapshot.atc_codes == ("N02C",)
    assert result.issues == ()


def test_an_atc_value_that_is_not_a_code_is_left_out_and_reported_never_guessed() -> None:
    result = mapped({"ATC Code 1": "UNCLASSIFIED PRODUCTS", "ATC Code 2": "A07CA"})

    assert result.snapshot.atc_codes == ("A07CA",)
    assert any("ATC" in issue and "UNCLASSIFIED PRODUCTS" in issue for issue in result.issues)


def test_without_the_arabic_page_the_arabic_fields_are_none() -> None:
    snapshot = mapped(ar=None).snapshot

    assert snapshot.trade_name_ar is None
    assert snapshot.dosage_form_ar is None
    assert snapshot.route_ar is None
    assert snapshot.storage_conditions_ar is None


def test_a_record_without_english_details_is_skipped() -> None:
    incomplete: dict[str, Any] = {"key": "x", "list": {}, "en": None, "ar": None, "provenance": {}}

    assert to_product_snapshot(incomplete, SAR) is None


def test_the_catalog_accepts_what_the_mapping_produces() -> None:
    data = snapshot_to_data(mapped().snapshot)

    assert data.trade_name.en == "ACME-ONE 5MG TAB"
    assert data.legal_status is not None
    assert data.legal_status.kind == "prescription"
    assert [p.name for p in data.manufacturers] == ["Maker A", "Maker B"]


def test_a_batch_reports_skipped_records_and_issues_per_key() -> None:
    from pharmavique.ingestion.infrastructure.connectors.sfda_web.mapping import map_records

    good = record()
    bad_price = {**record({"Price": "free"}), "key": "2-222-33"}
    no_english: dict[str, Any] = {
        "key": "3-333-44",
        "list": {},
        "en": None,
        "ar": None,
        "provenance": {},
    }

    batch = map_records([good, bad_price, no_english], SAR)

    assert [s.register_number for s in batch.snapshots] == ["1-111-22", "2-222-33"]
    assert batch.skipped == ("3-333-44",)
    assert list(batch.issues) == ["2-222-33"]


# ---- required labels (audit 2026-11, B1.1) ------------------------------------------------------
# A renamed label reads as "not stated" for every drug at once. The load checks the share of
# drugs missing each required label first, and refuses the whole run above the limit.


def test_the_required_labels_are_register_trade_scientific_and_price() -> None:
    assert REQUIRED_LABELS == ("Register Number", "Trade Name", "Scientific Name", "Price")


def test_records_missing_a_required_label_are_counted_per_label() -> None:
    renamed = {k: v for k, v in EN.items() if k != "Price"} | {"Unit Price": "9.5"}
    records = [
        record(),
        record(),
        {"key": "x", "en": rows(renamed)},
        {"key": "y", "en": rows({**EN, "Trade Name": "  "})},
        {"key": "z", "en": None},  # no English page: skipped by the load, not counted
    ]

    check = check_required_labels(records)

    assert check.records == 4
    assert check.missing == {"Price": 1, "Trade Name": 1}
    assert "Unit Price" in check.labels_seen
    assert check.failing(0.3) == {}
    assert check.failing(0.2) == {"Price": 0.25, "Trade Name": 0.25}


def test_an_empty_run_fails_nothing() -> None:
    check = check_required_labels([])

    assert check.records == 0
    assert check.failing(0.0) == {}
