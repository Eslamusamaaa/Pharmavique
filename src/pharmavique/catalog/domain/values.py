"""Value objects of the catalog domain. All frozen and validated in the constructor."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Self

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.money import Money
from pharmavique.shared_kernel.provenance import Provenance


def _clean(text: str | None) -> str | None:
    """Trim; blank means absent."""
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def _positive_decimal(value: Decimal | None, what: str) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal):
        raise InvariantViolation(f"{what} must be a Decimal, never a float")
    if not value.is_finite() or value <= 0:
        raise InvariantViolation(f"{what} must be a finite number above zero")


@dataclass(frozen=True, slots=True)
class ProductId:
    market: Market
    register_number: str

    def __post_init__(self) -> None:
        cleaned = _clean(self.register_number)
        if cleaned is None:
            raise InvariantViolation("register number must not be blank")
        object.__setattr__(self, "register_number", cleaned)


@dataclass(frozen=True, slots=True)
class LocalizedText:
    en: str | None = None
    ar: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "en", _clean(self.en))
        object.__setattr__(self, "ar", _clean(self.ar))
        if self.en is None and self.ar is None:
            raise InvariantViolation("localized text needs English or Arabic text")


@dataclass(frozen=True, slots=True)
class IngredientLine:
    """One active ingredient as the source names it, with its strength when it is known."""

    name: str
    strength: Decimal | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        cleaned = _clean(self.name)
        if cleaned is None:
            raise InvariantViolation("ingredient name must not be blank")
        object.__setattr__(self, "name", cleaned)
        _positive_decimal(self.strength, "ingredient strength")
        object.__setattr__(self, "unit", _clean(self.unit))


@dataclass(frozen=True, slots=True)
class Package:
    size: Decimal | None = None
    size_unit: str | None = None
    package_type: str | None = None
    package_size: int | None = None

    def __post_init__(self) -> None:
        _positive_decimal(self.size, "package size")
        if self.package_size is not None and self.package_size <= 0:
            raise InvariantViolation("package size must be above zero")
        object.__setattr__(self, "size_unit", _clean(self.size_unit))
        object.__setattr__(self, "package_type", _clean(self.package_type))


# Vocabularies hold only the values seen in the source so far. Anything else is kept verbatim
# with `kind=None`; it is never dropped and never mapped by guess.
LEGAL_STATUS: Mapping[str, str] = MappingProxyType({"prescription": "prescription", "otc": "otc"})
PRODUCT_CONTROL: Mapping[str, str] = MappingProxyType(
    {"uncontrolled": "uncontrolled", "controlled": "controlled", "restricted": "restricted"}
)
DISTRIBUTION_SITE: Mapping[str, str] = MappingProxyType(
    {"pharmacy": "pharmacy", "hospital": "hospital"}
)
AUTHORIZATION_STATUS: Mapping[str, str] = MappingProxyType({"valid": "valid"})
MARKETING_STATUS: Mapping[str, str] = MappingProxyType({"marketed": "marketed"})


@dataclass(frozen=True, slots=True)
class CodedValue:
    """A source value kept verbatim, plus the kind we recognise it as (if any)."""

    raw: str
    kind: str | None = None

    def __post_init__(self) -> None:
        cleaned = _clean(self.raw)
        if cleaned is None:
            raise InvariantViolation("coded value must not be blank")
        object.__setattr__(self, "raw", cleaned)

    @classmethod
    def of(cls, raw: str, vocabulary: Mapping[str, str]) -> Self:
        cleaned = _clean(raw)
        if cleaned is None:
            raise InvariantViolation("coded value must not be blank")
        return cls(cleaned, vocabulary.get(cleaned.lower()))


_ATC = re.compile(r"[A-Z](?:\d{2}(?:[A-Z](?:[A-Z](?:\d{2})?)?)?)?")


@dataclass(frozen=True, slots=True)
class AtcCode:
    """An ATC classification code at any level (for example `A07CA` or `S01BA04`)."""

    code: str

    def __post_init__(self) -> None:
        if not _ATC.fullmatch(self.code):
            raise InvariantViolation(f"not a valid ATC code: {self.code!r}")


@dataclass(frozen=True, slots=True)
class Party:
    """A manufacturer or marketing company."""

    name: str
    country: str | None = None

    def __post_init__(self) -> None:
        cleaned = _clean(self.name)
        if cleaned is None:
            raise InvariantViolation("party name must not be blank")
        object.__setattr__(self, "name", cleaned)
        object.__setattr__(self, "country", _clean(self.country))


@dataclass(frozen=True, slots=True)
class PricePoint:
    price: Money
    effective_from: datetime
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.effective_from.utcoffset() is None:
            raise InvariantViolation("price point time must be timezone-aware")
