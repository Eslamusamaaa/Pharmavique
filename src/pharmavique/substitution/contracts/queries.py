"""What other contexts may ask substitution: is this product equivalent to those?

Facts are plain values (as the catalog states them); the verdict comes from the equivalence rules
in this context's domain, never from a language model. Information for a pharmacist, not advice.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IngredientFacts:
    name: str
    strength: str | None  # decimal string as the source states it
    unit: str | None  # as the source states it, for example "mg" or "mg/5ml"


@dataclass(frozen=True, slots=True)
class ProductFacts:
    product_id: str
    ingredients: tuple[IngredientFacts, ...]
    dosage_form: str | None
    route: str | None = None  # as the source states it, for example "Intravenous use"
    trade_name: str | None = None  # its words can say a form the dosage form does not ("SOLUBLE")


@dataclass(frozen=True, slots=True)
class Comparison:
    product_id: str
    verdict: str  # "equivalent", "possible_needs_pharmacist_check" or "not_equivalent"
    ingredients: str  # "same", "different" or "unknown"
    strength: str
    form_family: str


class EquivalenceQueries(Protocol):
    def compare(self, base: ProductFacts, others: Sequence[ProductFacts]) -> tuple[Comparison, ...]:
        """One comparison per product in `others`, in the same order."""
        ...
