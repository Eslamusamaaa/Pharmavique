"""List the conditions each product's ingredients are contraindicated with, from a source."""

from collections.abc import Sequence

from pharmavique.interactions.application.ports import ContraindicationStore
from pharmavique.interactions.contracts.queries import (
    Contraindication,
    ContraindicationReport,
    ProductIngredients,
)
from pharmavique.interactions.domain.names import candidate_keys

__all__ = ["ListContraindications"]


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
        for register, name, keys in entries:
            for record in records:
                if record.ingredient in keys:
                    items.setdefault(
                        (register, name, record.disease),
                        Contraindication(
                            register, name, record.disease, record.text, record.source
                        ),
                    )
        ordered = sorted(items.values(), key=lambda i: (i.register_number, i.disease, i.ingredient))
        return ContraindicationReport(items=tuple(ordered), complete=False)
