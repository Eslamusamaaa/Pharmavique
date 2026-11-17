import json
from dataclasses import replace
from decimal import Decimal

from pharmavique.catalog.domain.product import ProductData
from pharmavique.catalog.domain.values import (
    AUTHORIZATION_STATUS,
    LEGAL_STATUS,
    MARKETING_STATUS,
    AtcCode,
    CodedValue,
    IngredientLine,
    LocalizedText,
    Package,
    Party,
)
from pharmavique.catalog.infrastructure.persistence.serialization import (
    data_from_json,
    data_to_json,
)
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.money import Money


def minimal() -> ProductData:
    return ProductData(
        trade_name=LocalizedText("ACME", None),
        ingredients=(IngredientLine("ACMEDRONE"),),
        dosage_form=LocalizedText("Tablet", None),
    )


def full() -> ProductData:
    return ProductData(
        trade_name=LocalizedText("ACME-ONE", "اكمي ون"),
        ingredients=(
            IngredientLine("SODIUM CHLORIDE", Decimal("0.52"), "g"),
            IngredientLine("DEXTROSE", Decimal("2.7"), "g"),
        ),
        dosage_form=LocalizedText("Powder", "مسحوق"),
        route=LocalizedText("Oral use", "استخدام فموي"),
        package=Package(Decimal("5.5"), "ml", "Sachet", 10),
        legal_status=CodedValue.of("Prescription", LEGAL_STATUS),
        product_control=CodedValue("Special", None),
        distribution_site=None,
        authorization_status=CodedValue.of("Valid", AUTHORIZATION_STATUS),
        marketing_status=CodedValue.of("Marketed", MARKETING_STATUS),
        atc_codes=(AtcCode("A07CA"), AtcCode("S01BA04")),
        shelf_life="24",
        storage_conditions=LocalizedText("store below 25c", "يحفظ تحت 25"),
        manufacturers=(Party("Maker A", "Atlantis"), Party("Maker B")),
        marketing_company=Party("Maker A", "Atlantis"),
        agents=("AGENT ONE", "AGENT TWO"),
        description_code="7000-1",
        price=Money(Decimal("9.50"), Currency.owner_assumed("SAR")),
    )


def test_a_fully_populated_product_survives_a_round_trip() -> None:
    data = full()

    restored = data_from_json(json.loads(json.dumps(data_to_json(data))))

    # the price lives in its own columns, so the document never carries it
    assert restored == replace(data, price=None)


def test_a_minimal_product_survives_a_round_trip() -> None:
    data = minimal()

    assert data_from_json(json.loads(json.dumps(data_to_json(data)))) == data


def test_the_price_is_not_part_of_the_json_because_it_has_its_own_columns() -> None:
    assert "price" not in data_to_json(full())


def test_decimals_are_stored_as_text_so_no_precision_is_lost() -> None:
    document = data_to_json(full())

    assert document["ingredients"][0]["strength"] == "0.52"
    assert document["package"]["size"] == "5.5"


def test_unrecognised_coded_values_keep_their_raw_text_and_no_kind() -> None:
    restored = data_from_json(json.loads(json.dumps(data_to_json(full()))))

    assert restored.product_control == CodedValue("Special", None)


def test_unknown_future_keys_in_the_document_are_ignored() -> None:
    document = json.loads(json.dumps(data_to_json(minimal())))
    document["something_added_later"] = {"x": 1}

    assert data_from_json(document) == minimal()
