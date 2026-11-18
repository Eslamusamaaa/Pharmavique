"""Turn catalog facts into product specs and assess them with the equivalence rules.

Conservative on purpose: an ingredient is identified by its normalized name, a strength is only
read when its unit is one the domain knows, and two dosage forms count as one family only when
they are written the same. Everything else is "unknown", which can never yield "equivalent".
"""

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.substitution.contracts.queries import Comparison, ProductFacts
from pharmavique.substitution.domain.equivalence import assess
from pharmavique.substitution.domain.spec import DosageFormFamily, IngredientStrength, ProductSpec
from pharmavique.substitution.domain.strength import Quantity, Strength, Unit

_MASS_UNITS = {"mcg": Unit.MCG, "µg": Unit.MCG, "ug": Unit.MCG, "mg": Unit.MG, "g": Unit.G}
_UNIT = re.compile(r"^\s*(mcg|µg|ug|mg|g|iu)\s*(?:/\s*(\d+(?:\.\d+)?)?\s*(ml|l))?\s*$")


def _normalized(text: str) -> str:
    return " ".join(text.upper().split())


def _decimal(text: str) -> Decimal | None:
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError):
        return None
    return value if value.is_finite() and value > 0 else None


def parse_strength(amount: str | None, unit: str | None) -> Strength | None:
    """A strength the domain can compare, or None when it cannot be read without guessing."""
    if amount is None or unit is None:
        return None
    value = _decimal(amount)
    match = _UNIT.match(unit.lower())
    if value is None or match is None:
        return None
    mass, volume_amount, volume_unit = match.groups()
    numerator = Quantity(value, Unit.IU if mass == "iu" else _MASS_UNITS[mass])
    if volume_unit is None:
        return Strength(numerator)
    per_amount = _decimal(volume_amount) if volume_amount else Decimal(1)
    if per_amount is None:
        return None
    return Strength(numerator, Quantity(per_amount, Unit.ML if volume_unit == "ml" else Unit.L))


def _spec(facts: ProductFacts, family: DosageFormFamily | None) -> ProductSpec | None:
    names = [_normalized(i.name) for i in facts.ingredients]
    if not names or len(names) != len(set(names)):
        return None  # empty or repeated lines: not something the rules can compare
    try:
        return ProductSpec(
            product_id=facts.product_id,
            ingredients=tuple(
                IngredientStrength(name, parse_strength(i.strength, i.unit))
                for name, i in zip(names, facts.ingredients, strict=True)
            ),
            form_family=family,
        )
    except InvariantViolation:
        return None


class CompareProductsHandler:
    """Implements `EquivalenceQueries` with the domain's `assess`."""

    def compare(self, base: ProductFacts, others: Sequence[ProductFacts]) -> tuple[Comparison, ...]:
        base_form = _normalized(base.dosage_form) if base.dosage_form else None
        base_family = DosageFormFamily(base_form) if base_form else None
        base_spec = _spec(base, base_family)
        results: list[Comparison] = []
        for other in others:
            other_form = _normalized(other.dosage_form) if other.dosage_form else None
            # Same written form: same family. Different wording: unknown (a pharmacist decides).
            family = base_family if base_form is not None and other_form == base_form else None
            other_spec = _spec(other, family)
            if base_spec is None or other_spec is None:
                results.append(
                    Comparison(
                        other.product_id,
                        "possible_needs_pharmacist_check",
                        "unknown",
                        "unknown",
                        "unknown",
                    )
                )
                continue
            outcome = assess(base_spec, other_spec)
            results.append(
                Comparison(
                    other.product_id,
                    outcome.verdict.value,
                    outcome.ingredients.value,
                    outcome.strength.value,
                    outcome.form_family.value,
                )
            )
        return tuple(results)
