"""What substitution needs to know about a product, in this context's own terms.

The catalog context supplies the data through an adapter; nothing here imports it.
"""

from dataclasses import dataclass

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.substitution.domain.strength import Strength


@dataclass(frozen=True, slots=True)
class DosageFormFamily:
    """A group of dosage forms that count as interchangeable.

    Which forms belong to one family is a pharmaceutical decision that arrives as reference data
    (to be reviewed by a pharmacist). This type deliberately does not enumerate families.
    """

    code: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise InvariantViolation("dosage form family code must not be blank")


@dataclass(frozen=True, slots=True)
class IngredientStrength:
    """One active ingredient of a product.

    `ingredient_id` is None when the ingredient could not be resolved to a canonical id, and
    `strength` is None when it is missing or could not be parsed. Both mean "unknown",
    never a guess.
    """

    ingredient_id: str | None
    strength: Strength | None

    def __post_init__(self) -> None:
        if self.ingredient_id is not None and not self.ingredient_id.strip():
            raise InvariantViolation("ingredient id must not be blank; use None when unresolved")


@dataclass(frozen=True, slots=True)
class ProductSpec:
    product_id: str
    ingredients: tuple[IngredientStrength, ...]
    form_family: DosageFormFamily | None  # None means unknown

    def __post_init__(self) -> None:
        if not self.product_id.strip():
            raise InvariantViolation("product id must not be blank")
        if not self.ingredients:
            raise InvariantViolation("a product needs at least one active ingredient")
        resolved = [i.ingredient_id for i in self.ingredients if i.ingredient_id is not None]
        if len(resolved) != len(set(resolved)):
            raise InvariantViolation("a product must not list the same ingredient twice")
