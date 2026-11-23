"""Strengths written in a listing's text ("500 mg", "0.5 g", "5 mg/5 ml", "0.05%"), made comparable.

Two strengths are equal only when they are the same amount of the same kind after unit conversion:
500 mg and 0.5 g are equal; 500 mg and 500 IU are not; "100 mg" and "100 mg/ml" are not. A text with
no strength gives no strengths, which means "unknown", never "zero".
"""

import re
from dataclasses import dataclass
from decimal import Decimal

__all__ = ["Strength", "parse_strengths"]

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")  # noqa: RUF001
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_NUMBER = r"(\d+(?:\.\d+)?)"
_UNIT = r"(mcg|mg|µg|μg|ug|gms?|g|iu|ملجم|مجم|ملغ|ميكروجرام|جم|%)"
_PER = r"(?:\s*/\s*" + _NUMBER + r"?\s*(ml|مل|l)(?![a-z]))?"
_STRENGTH = re.compile(_NUMBER + r"\s*" + _UNIT + r"(?![a-z])" + _PER)

_TO_MG = {
    "mg": Decimal(1), "ملجم": Decimal(1), "مجم": Decimal(1), "ملغ": Decimal(1),
    "g": Decimal(1000), "gm": Decimal(1000), "gms": Decimal(1000), "جم": Decimal(1000),
    "mcg": Decimal("0.001"), "µg": Decimal("0.001"), "μg": Decimal("0.001"),
    "ug": Decimal("0.001"), "ميكروجرام": Decimal("0.001"),
}  # fmt: skip
_TO_ML = {"ml": Decimal(1), "مل": Decimal(1), "l": Decimal(1000)}


@dataclass(frozen=True, slots=True)
class Strength:
    kind: str  # "mass" (mg), "iu", "percent", or one of those with "_per_ml"
    value: Decimal


def _clean(text: str) -> str:
    return _DECIMAL_COMMA.sub(".", text.translate(_DIGITS)).lower()


def parse_strengths(text: str) -> tuple[Strength, ...]:
    """Every strength the text writes, in order, without repeats."""
    found: list[Strength] = []
    for match in _STRENGTH.finditer(_clean(text)):
        amount = Decimal(match.group(1))
        unit = match.group(2)
        if unit == "iu":
            kind = "iu"
        elif unit == "%":
            kind = "percent"
        else:
            kind, amount = "mass", amount * _TO_MG[unit]
        per_unit = match.group(4)
        if per_unit is not None and kind != "percent":
            per_amount = Decimal(match.group(3)) if match.group(3) else Decimal(1)
            amount = amount / (per_amount * _TO_ML[per_unit])
            kind += "_per_ml"
        strength = Strength(kind, amount.normalize())
        if strength not in found:
            found.append(strength)
    return tuple(found)
