"""One recorded interaction between two ingredients, as an interaction source states it."""

from dataclasses import dataclass

from pharmavique.interactions.domain.severity import Severity


@dataclass(frozen=True, slots=True)
class InteractionRecord:
    ingredient_a: str  # normalized key; always sorts before ingredient_b
    ingredient_b: str
    severity: Severity
    source: str  # for example "ddinter-2.0"

    def __post_init__(self) -> None:
        if self.ingredient_a > self.ingredient_b:
            raise ValueError("ingredient_a must sort before ingredient_b")
