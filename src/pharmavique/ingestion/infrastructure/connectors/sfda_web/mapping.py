"""Anti-corruption layer: a stored SFDA record becomes the catalog's `ProductSnapshot`.

SFDA's page layout stops here. The catalog never sees label names, combined "a,b,c" cells or
"Name: X | Country: Y" lines. The rule for anything unclear is the same everywhere: keep the
source text, record an issue, and never guess. For example, ingredient names are only paired with
strengths when the two lists have the same length and every strength is a readable number.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from pharmavique.catalog.contracts.commands import IngredientLineDto, PartyDto, ProductSnapshot
from pharmavique.shared_kernel.currency import Currency
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money

# English labels, exactly as the pages show them.
_REGISTER = "Register Number"
_TRADE_NAME = "Trade Name"
_SCIENTIFIC = "Scientific Name"
_STRENGTH = "Strength"
_STRENGTH_UNIT = "Strength Unit"
_FORM = "Dosage Form"
_ROUTE = "Route of Administration"
_SIZE = "Size"
_SIZE_UNIT = "Size Unit"
_PACKAGE_TYPE = "Package Type"
_PACKAGE_SIZE = "Package Size"
_LEGAL = "Legal Status"
_CONTROL = "Product Control"
_SITE = "Distribution Site"
_SHELF_LIFE = "Shelf Life"
_STORAGE = "Storage Conditions"
_MANUFACTURERS = "Manufacturers"
_MARKETING_COMPANY = "Marketing Company"
_MARKETING_COUNTRY = "Country of marketing company"
_AGENTS = "Agents"
_ATC_1 = "ATC Code 1"
_ATC_2 = "ATC Code 2"
_DESCRIPTION = "Description Code"
_AUTHORIZATION = "Authorization Status"
_MARKETING_STATUS = "Marketing Status"
_PRICE = "Price"

# Arabic labels used for the Arabic text fields.
_AR_TRADE_NAME = "الاسم التجاري"
_AR_FORM = "الشكل الصيدلاني"
_AR_ROUTE = "طريقة الإستعمال"
_AR_STORAGE = "ظروف التخزين"

_MANUFACTURER_LINE = re.compile(r"^Name:\s*(?P<name>.*?)\s*\|\s*Country:\s*(?P<country>.*)$", re.I)


@dataclass(frozen=True, slots=True)
class MappedProduct:
    snapshot: ProductSnapshot
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappedBatch:
    snapshots: tuple[ProductSnapshot, ...]
    skipped: tuple[str, ...]  # keys of records with no English details
    issues: Mapping[str, tuple[str, ...]]  # per key, only keys that have issues


def _labelled(section: Iterable[Mapping[str, str]] | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in section or ():
        values.setdefault(item["label"], item["value"])
    return values


def _text(fields: Mapping[str, str], label: str) -> str | None:
    value = fields.get(label)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _lines(fields: Mapping[str, str], label: str) -> list[str]:
    return [line.strip() for line in (fields.get(label) or "").split("\n") if line.strip()]


def _decimal(text: str | None, *, allow_zero: bool = False) -> Decimal | None:
    if text is None:
        return None
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
        return None
    return value


def _ingredients(
    names_text: str | None,
    strengths_text: str | None,
    unit_text: str | None,
    issues: list[str],
) -> tuple[IngredientLineDto, ...]:
    whole = (names_text or "").strip()
    if not whole:
        issues.append("ingredient: the scientific name is missing")
        return ()
    names = [part.strip() for part in whole.split(",") if part.strip()]
    strengths = [part.strip() for part in (strengths_text or "").split(",") if part.strip()]
    unit = unit_text.strip() if unit_text and unit_text.strip() else None

    if len(names) == 1 and len(strengths) <= 1:
        if not strengths:
            return (IngredientLineDto(whole),)
        value = _decimal(strengths[0])
        if value is None:
            issues.append(f"ingredient strength is not readable: {strengths[0]!r}")
            return (IngredientLineDto(whole),)
        return (IngredientLineDto(whole, value, unit),)

    if strengths and len(names) == len(strengths):
        values = [_decimal(s) for s in strengths]
        if all(v is not None for v in values):
            return tuple(
                IngredientLineDto(name, value, unit)
                for name, value in zip(names, values, strict=True)
            )
        issues.append(f"ingredient strengths are not all readable: {strengths_text!r}")
        return (IngredientLineDto(whole),)

    issues.append(
        f"ingredient names and strengths do not line up: {len(names)} names, "
        f"{len(strengths)} strengths; kept as one line"
    )
    return (IngredientLineDto(whole),)


def _manufacturers(lines: list[str]) -> tuple[PartyDto, ...]:
    parties: list[PartyDto] = []
    for line in lines:
        match = _MANUFACTURER_LINE.match(line)
        if match and match.group("name"):
            country = match.group("country").strip() or None
            parties.append(PartyDto(match.group("name"), country))
        else:
            parties.append(PartyDto(line))
    return tuple(parties)


# The ATC field sometimes carries the code and its description together ("N02C-ANTIMIGRAINE ...").
_ATC_SHAPE = re.compile(r"[A-Z](?:\d{2}(?:[A-Z](?:[A-Z](?:\d{2})?)?)?)?")
_LEADING_WORD = re.compile(r"[A-Za-z0-9]+")


def _atc_codes(values: Iterable[str | None], issues: list[str]) -> tuple[str, ...]:
    """The code in front of each ATC value. A value with no code in it is left out and reported."""
    codes: list[str] = []
    for value in values:
        if not value:
            continue
        leading = _LEADING_WORD.match(value.strip())
        code = leading.group(0).upper() if leading else ""
        if _ATC_SHAPE.fullmatch(code):
            codes.append(code)
        else:
            issues.append(f"ATC value has no readable code: {value!r}")
    return tuple(codes)


def to_product_snapshot(
    record: Mapping[str, Any], price_currency: Currency
) -> MappedProduct | None:
    """Map one stored record. Returns None when the record has no English details page."""
    if not record.get("en"):
        return None
    issues: list[str] = []
    en = _labelled(record["en"])
    ar = _labelled(record.get("ar"))

    price: Money | None = None
    price_text = _text(en, _PRICE)
    if price_text is not None:
        amount = _decimal(price_text, allow_zero=True)
        if amount is None:
            issues.append(f"price is not readable: {price_text!r}")
        else:
            price = Money(amount, price_currency)

    package_count: int | None = None
    count_text = _text(en, _PACKAGE_SIZE)
    if count_text is not None:
        count = _decimal(count_text)
        if count is None or count != count.to_integral_value():
            issues.append(f"package size is not a whole number: {count_text!r}")
        else:
            package_count = int(count)

    marketing_name = _text(en, _MARKETING_COMPANY)
    snapshot = ProductSnapshot(
        market=Market.SA,
        register_number=str(record["key"]),
        trade_name_en=_text(en, _TRADE_NAME),
        trade_name_ar=_text(ar, _AR_TRADE_NAME),
        ingredients=_ingredients(
            _text(en, _SCIENTIFIC), _text(en, _STRENGTH), _text(en, _STRENGTH_UNIT), issues
        ),
        dosage_form_en=_text(en, _FORM),
        dosage_form_ar=_text(ar, _AR_FORM),
        route_en=_text(en, _ROUTE),
        route_ar=_text(ar, _AR_ROUTE),
        package_size=_decimal(_text(en, _SIZE)),
        package_size_unit=_text(en, _SIZE_UNIT),
        package_type=_text(en, _PACKAGE_TYPE),
        package_count=package_count,
        legal_status=_text(en, _LEGAL),
        product_control=_text(en, _CONTROL),
        distribution_site=_text(en, _SITE),
        authorization_status=_text(en, _AUTHORIZATION),
        marketing_status=_text(en, _MARKETING_STATUS),
        atc_codes=_atc_codes((_text(en, _ATC_1), _text(en, _ATC_2)), issues),
        shelf_life=_text(en, _SHELF_LIFE),
        storage_conditions_en=_text(en, _STORAGE),
        storage_conditions_ar=_text(ar, _AR_STORAGE),
        manufacturers=_manufacturers(_lines(en, _MANUFACTURERS)),
        marketing_company=(
            PartyDto(marketing_name, _text(en, _MARKETING_COUNTRY)) if marketing_name else None
        ),
        agents=tuple(_lines(en, _AGENTS)),
        description_code=_text(en, _DESCRIPTION),
        price=price,
    )
    return MappedProduct(snapshot, tuple(issues))


def map_records(records: Iterable[Mapping[str, Any]], price_currency: Currency) -> MappedBatch:
    snapshots: list[ProductSnapshot] = []
    skipped: list[str] = []
    issues: dict[str, tuple[str, ...]] = {}
    for record in records:
        mapped = to_product_snapshot(record, price_currency)
        if mapped is None:
            skipped.append(str(record["key"]))
            continue
        snapshots.append(mapped.snapshot)
        if mapped.issues:
            issues[mapped.snapshot.register_number] = mapped.issues
    return MappedBatch(tuple(snapshots), tuple(skipped), issues)


# ---- required labels (audit 2026-11, B1.1) ------------------------------------------------------
# When SFDA renames or drops one of these labels, every drug reads as "not stated" at once. The
# load counts them before it writes anything and refuses the run above a share (measured on the
# full crawl of 2026-11-16: 9,145 drugs, one without a scientific name, none without the others).
REQUIRED_LABELS = (_REGISTER, _TRADE_NAME, _SCIENTIFIC, _PRICE)


@dataclass(frozen=True, slots=True)
class LabelCheck:
    records: int  # records with an English details page
    missing: Mapping[str, int]  # per required label, records without it (absent or blank)
    labels_seen: frozenset[str]  # every English label met: the run's page shape

    def failing(self, max_share: float) -> dict[str, float]:
        """The required labels missing from more than `max_share` of the records, with the share."""
        if not self.records:
            return {}
        shares = {label: count / self.records for label, count in self.missing.items()}
        return {label: share for label, share in shares.items() if share > max_share}


def check_required_labels(records: Iterable[Mapping[str, Any]]) -> LabelCheck:
    total = 0
    missing: dict[str, int] = {}
    seen: set[str] = set()
    for record in records:
        if not record.get("en"):
            continue
        total += 1
        en = _labelled(record["en"])
        seen.update(en)
        for label in REQUIRED_LABELS:
            if _text(en, label) is None:
                missing[label] = missing.get(label, 0) + 1
    return LabelCheck(total, missing, frozenset(seen))
