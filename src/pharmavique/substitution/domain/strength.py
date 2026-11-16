"""Strength value objects and exact unit normalization.

Normalization uses `Fraction`, so ratios such as 1 mg / 3 ml stay exact and equality is never
decided by rounding. Parsing source strings into these types belongs to ingestion, after we have
seen real SFDA data; this module only defines what "the same strength" means.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

from pharmavique.shared_kernel.errors import InvariantViolation


class Unit(StrEnum):
    MCG = "mcg"
    MG = "mg"
    G = "g"
    IU = "iu"  # international unit
    ML = "ml"
    L = "l"


class Dimension(StrEnum):
    MASS = "mass"
    INTERNATIONAL_UNIT = "international_unit"


_MASS_IN_MG = {
    Unit.MCG: Fraction(1, 1000),
    Unit.MG: Fraction(1),
    Unit.G: Fraction(1000),
}
_VOLUME_IN_ML = {
    Unit.ML: Fraction(1),
    Unit.L: Fraction(1000),
}


@dataclass(frozen=True, slots=True)
class Quantity:
    amount: Decimal
    unit: Unit

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise InvariantViolation("quantity amount must be a Decimal, never a float")
        if not self.amount.is_finite() or self.amount <= 0:
            raise InvariantViolation("quantity amount must be a finite number above zero")


@dataclass(frozen=True, slots=True)
class NormalizedStrength:
    """Canonical form: mg (or IU) for the dimension, divided by ml when `per_volume`."""

    dimension: Dimension
    per_volume: bool
    value: Fraction


@dataclass(frozen=True, slots=True)
class Strength:
    """A total amount (for example 500 mg) or a concentration (for example 250 mg per 5 ml)."""

    numerator: Quantity
    per: Quantity | None = None

    def __post_init__(self) -> None:
        if self.numerator.unit not in _MASS_IN_MG and self.numerator.unit is not Unit.IU:
            raise InvariantViolation("strength numerator must be a mass or an international unit")
        if self.per is not None and self.per.unit not in _VOLUME_IN_ML:
            raise InvariantViolation("strength denominator must be a volume")

    def normalized(self) -> NormalizedStrength:
        amount = Fraction(self.numerator.amount)
        if self.numerator.unit is Unit.IU:
            dimension = Dimension.INTERNATIONAL_UNIT
            base = amount
        else:
            dimension = Dimension.MASS
            base = amount * _MASS_IN_MG[self.numerator.unit]

        if self.per is None:
            return NormalizedStrength(dimension, per_volume=False, value=base)

        volume_ml = Fraction(self.per.amount) * _VOLUME_IN_ML[self.per.unit]
        return NormalizedStrength(dimension, per_volume=True, value=base / volume_ml)
