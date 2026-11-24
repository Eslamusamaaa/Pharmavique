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


# Words in a trade name that say how the product is released or taken. The registry sometimes
# writes the same plain dosage form for both ("Tablet" for PANADOL SOLUBLE and for a plain tablet,
# "Tablet" for an enteric-coated RAZON): two names that differ here are never called equivalent.
_RELEASE_WORDS = {
    "soluble": "soluble", "effervescent": "effervescent", "eff": "effervescent",
    "dispersible": "dispersible", "orodispersible": "orodispersible", "odt": "orodispersible",
    "chewable": "chewable", "sublingual": "sublingual",
    "ec": "enteric", "enteric": "enteric", "gastro": "enteric", "delayed": "modified",
    "retard": "modified", "sr": "modified", "xr": "modified", "er": "modified", "xl": "modified",
    "mr": "modified", "cr": "modified", "la": "modified", "prolonged": "modified",
    "extended": "modified", "sustained": "modified", "controlled": "modified",
    "modified": "modified", "depot": "modified",
    # the device: a vial, a pre-filled pen or syringe, a cartridge, an inhaler
    "pen": "pen", "solostar": "pen", "flexpen": "pen", "kwikpen": "pen", "flextouch": "pen",
    "penfill": "cartridge", "cartridge": "cartridge", "syringe": "syringe", "pfs": "syringe",
    "prefilled": "syringe", "vial": "vial", "ampoule": "ampoule", "amp": "ampoule",
    "inhaler": "inhaler", "evohaler": "inhaler", "diskus": "inhaler", "turbuhaler": "inhaler",
    "accuhaler": "inhaler", "ellipta": "inhaler", "respimat": "inhaler", "nebuliser": "nebuliser",
    "nebulizer": "nebuliser",
}  # fmt: skip
# Biologics: two brands of one biologic are biosimilars, and whether one may replace another is a
# decision for the pharmacist or doctor, never a computed "equivalent".
_BIOLOGIC = re.compile(
    r"mab\b|cept\b|insulin|filgrastim|epoetin|somatropin|interferon|octocog|nonacog|follitropin"
    r"|teriparatide|\balfa\b|\bbeta\b|factor",
    re.IGNORECASE,
)
# Strengths printed in a trade name: "500 mg", "1 G", "16/12.5MG", "0.016 G/12.5 MG".
_NAME_STRENGTH = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:(mg|mcg|µg|ug|gm|g|iu|i\.u)\b)?\s*/\s*(\d+(?:\.\d+)?)\s*"
    r"(mg|mcg|µg|ug|gm|g|iu|i\.u)\b|(\d+(?:\.\d+)?)\s*(mg|mcg|µg|ug|gm|g|iu|i\.u)\b",
    re.IGNORECASE,
)
_TO_MG = {"mg": Decimal(1), "mcg": Decimal("0.001"), "µg": Decimal("0.001"),
          "ug": Decimal("0.001"), "g": Decimal(1000), "gm": Decimal(1000)}  # fmt: skip


def _amount(number: str, unit: str) -> str:
    """One printed amount in one scale: masses in mg, units as written ("1 G" is "1000")."""
    unit = unit.lower().replace(".", "")
    value = Decimal(number) * _TO_MG.get(unit, Decimal(1))
    return format(value.normalize(), "f")


def _printed_strengths(trade_name: str | None) -> frozenset[str]:
    found: set[str] = set()
    for first, first_unit, second, second_unit, alone, alone_unit in _NAME_STRENGTH.findall(
        trade_name or ""
    ):
        if alone:
            found.add(_amount(alone, alone_unit))
        else:
            found.add(_amount(first, first_unit or second_unit))
            found.add(_amount(second, second_unit))
    return frozenset(found)


def _registry_strengths(facts: ProductFacts) -> frozenset[str]:
    """Each registered strength, and their total: names often print the total of a combination
    ("AUGMENTIN 1 G" is 875 mg + 125 mg, "CO-IRBETEL 312.5" is 300 mg + 12.5 mg)."""
    found: set[str] = set()
    for line in facts.ingredients:
        value = _decimal(line.strength or "")
        unit = (line.unit or "").lower().split("/")[0].strip()
        if value is not None and unit:
            found.add(_amount(str(value), unit))
    if len(found) > 1:
        found.add(format(sum((Decimal(v) for v in found), Decimal(0)).normalize(), "f"))
    return frozenset(found)


def _name_agrees(facts: ProductFacts) -> bool:
    """Every strength printed in the name is one of the registry's strengths. The registry itself
    is sometimes wrong (GARDIA PLUS 8/12.5 is recorded with 16 mg): such a product is never called
    equivalent on the registry's numbers alone."""
    printed = _printed_strengths(facts.trade_name)
    return not printed or printed <= _registry_strengths(facts)


def _biologic(facts: ProductFacts) -> bool:
    return any(_BIOLOGIC.search(line.name) for line in facts.ingredients)


_WORD = re.compile(r"[a-z]+")


def _release(trade_name: str | None) -> frozenset[str] | None:
    """The release and form words of a name ("E.C" reads as "ec"); None when there is no name."""
    if not trade_name:
        return None
    words = _WORD.findall(trade_name.lower().replace(".", ""))
    return frozenset(_RELEASE_WORDS[w] for w in words if w in _RELEASE_WORDS)


def _same_route(a: str | None, b: str | None) -> bool:
    """Both routes unknown or written the same. One known and one not counts as different."""
    if a is None and b is None:
        return True
    return a is not None and b is not None and _normalized(a) == _normalized(b)


def _same_presentation(base: ProductFacts, other: ProductFacts) -> bool:
    """The same route, the same release and device words in the names, no biologic, and names
    whose printed strengths agree with the registry: an IV and an IM vial of one drug, a soluble and
    a plain tablet, a vial and a pen, or two biosimilars are for a pharmacist to judge."""
    if not _same_route(base.route, other.route):
        return False
    if _biologic(base) or _biologic(other):
        return False
    if not (_name_agrees(base) and _name_agrees(other)):
        return False
    mine, theirs = _release(base.trade_name), _release(other.trade_name)
    return mine is None or theirs is None or mine == theirs


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
            # A different route or release word in the name: unknown too.
            same = base_form is not None and other_form == base_form
            family = base_family if same and _same_presentation(base, other) else None
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
