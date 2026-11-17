"""`ProductData` to and from a JSON document (stored in a JSONB column).

Decimals are written as text so no precision is lost. The price is not part of the document: it
has its own columns, so it can be queried. Reading ignores unknown keys, so a newer writer never
breaks an older reader.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pharmavique.catalog.domain.product import ProductData
from pharmavique.catalog.domain.values import (
    AtcCode,
    CodedValue,
    IngredientLine,
    LocalizedText,
    Package,
    Party,
)


def _decimal_out(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal_in(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _text_out(text: LocalizedText | None) -> dict[str, str | None] | None:
    return None if text is None else {"en": text.en, "ar": text.ar}


def _text_in(raw: Mapping[str, Any] | None) -> LocalizedText | None:
    return None if raw is None else LocalizedText(raw.get("en"), raw.get("ar"))


def _coded_out(value: CodedValue | None) -> dict[str, str | None] | None:
    return None if value is None else {"raw": value.raw, "kind": value.kind}


def _coded_in(raw: Mapping[str, Any] | None) -> CodedValue | None:
    return None if raw is None else CodedValue(raw["raw"], raw.get("kind"))


def _party_out(party: Party | None) -> dict[str, str | None] | None:
    return None if party is None else {"name": party.name, "country": party.country}


def _party_in(raw: Mapping[str, Any] | None) -> Party | None:
    return None if raw is None else Party(raw["name"], raw.get("country"))


def data_to_json(data: ProductData) -> dict[str, Any]:
    return {
        "trade_name": _text_out(data.trade_name),
        "ingredients": [
            {"name": i.name, "strength": _decimal_out(i.strength), "unit": i.unit}
            for i in data.ingredients
        ],
        "dosage_form": _text_out(data.dosage_form),
        "route": _text_out(data.route),
        "package": {
            "size": _decimal_out(data.package.size),
            "size_unit": data.package.size_unit,
            "package_type": data.package.package_type,
            "package_size": data.package.package_size,
        },
        "legal_status": _coded_out(data.legal_status),
        "product_control": _coded_out(data.product_control),
        "distribution_site": _coded_out(data.distribution_site),
        "authorization_status": _coded_out(data.authorization_status),
        "marketing_status": _coded_out(data.marketing_status),
        "atc_codes": [code.code for code in data.atc_codes],
        "shelf_life": data.shelf_life,
        "storage_conditions": _text_out(data.storage_conditions),
        "manufacturers": [_party_out(p) for p in data.manufacturers],
        "marketing_company": _party_out(data.marketing_company),
        "agents": list(data.agents),
        "description_code": data.description_code,
    }


def data_from_json(document: Mapping[str, Any]) -> ProductData:
    """Rebuild the product data. The price is left empty; the repository fills it in."""
    package = document.get("package") or {}
    trade_name = _text_in(document["trade_name"])
    dosage_form = _text_in(document["dosage_form"])
    assert trade_name is not None  # noqa: S101 (written by data_to_json, which always sets both)
    assert dosage_form is not None  # noqa: S101
    return ProductData(
        trade_name=trade_name,
        ingredients=tuple(
            IngredientLine(i["name"], _decimal_in(i.get("strength")), i.get("unit"))
            for i in document["ingredients"]
        ),
        dosage_form=dosage_form,
        route=_text_in(document.get("route")),
        package=Package(
            _decimal_in(package.get("size")),
            package.get("size_unit"),
            package.get("package_type"),
            package.get("package_size"),
        ),
        legal_status=_coded_in(document.get("legal_status")),
        product_control=_coded_in(document.get("product_control")),
        distribution_site=_coded_in(document.get("distribution_site")),
        authorization_status=_coded_in(document.get("authorization_status")),
        marketing_status=_coded_in(document.get("marketing_status")),
        atc_codes=tuple(AtcCode(code) for code in document.get("atc_codes", ())),
        shelf_life=document.get("shelf_life"),
        storage_conditions=_text_in(document.get("storage_conditions")),
        manufacturers=tuple(
            party
            for party in (_party_in(raw) for raw in document.get("manufacturers", ()))
            if party is not None
        ),
        marketing_company=_party_in(document.get("marketing_company")),
        agents=tuple(document.get("agents", ())),
        description_code=document.get("description_code"),
    )
