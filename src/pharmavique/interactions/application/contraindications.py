"""List the conditions each product's ingredients are contraindicated with, from a source."""

import re
from collections.abc import Sequence

from pharmavique.interactions.application.ports import ContraindicationStore
from pharmavique.interactions.contracts.queries import (
    Contraindication,
    ContraindicationReport,
    ProductIngredients,
)
from pharmavique.interactions.domain.names import candidate_keys

__all__ = ["ListContraindications"]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def names_the_condition(disease: str, text: str) -> bool:
    """True only when the label text itself contains the condition's name.

    MeDIC maps label sentences to ontology names by software; a row whose own text does not say
    the condition is not shown, because we cannot tell a correct mapping from a wrong one.
    """
    return _squash(disease) in _squash(text)


class ListContraindications:
    def __init__(self, store: ContraindicationStore) -> None:
        self._store = store

    async def run(self, products: Sequence[ProductIngredients]) -> ContraindicationReport:
        entries = [
            (p.register_number, name, set(candidate_keys(name)))
            for p in products
            for name in p.ingredients
        ]
        every_key = {key for _, _, keys in entries for key in keys}
        records = await self._store.for_ingredients(every_key)
        items: dict[tuple[str, str, str], Contraindication] = {}
        hidden: set[tuple[str, str, str]] = set()
        for register, name, keys in entries:
            for record in records:
                if record.ingredient in keys:
                    if not names_the_condition(record.disease, record.text):
                        hidden.add((register, record.ingredient, record.disease))
                        continue
                    # one row per substance, even when the registry names it twice
                    # ("ACETYLSALICYLIC ACID" and "ASPIRIN" are one key)
                    items.setdefault(
                        (register, record.ingredient, record.disease),
                        Contraindication(
                            register, name, record.disease, record.text, record.source
                        ),
                    )
        ordered = sorted(items.values(), key=lambda i: (i.register_number, i.disease, i.ingredient))
        return ContraindicationReport(
            items=tuple(ordered), complete=False, hidden_unverified=len(hidden - set(items))
        )
