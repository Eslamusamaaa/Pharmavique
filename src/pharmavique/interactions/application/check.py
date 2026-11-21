"""Check a set of products: recorded interactions, duplicated ingredients, what cannot be judged."""

from collections.abc import Sequence
from itertools import combinations

from pharmavique.interactions.application.ports import InteractionStore
from pharmavique.interactions.contracts.queries import (
    Finding,
    InteractionReport,
    ProductIngredients,
)
from pharmavique.interactions.domain.names import base_key, candidate_keys
from pharmavique.interactions.domain.severity import Severity

__all__ = ["CheckInteractions", "ProductIngredients"]

_KIND_RANK = {"interaction": 0, "duplicate_ingredient": 1}


class CheckInteractions:
    def __init__(self, store: InteractionStore) -> None:
        self._store = store

    async def run(self, products: Sequence[ProductIngredients]) -> InteractionReport:
        entries = [
            (p.register_number, name, candidate_keys(name))
            for p in products
            for name in p.ingredients
        ]
        every_key = {key for _, _, keys in entries for key in keys}
        known = await self._store.known(every_key)
        records = await self._store.pairs_among(every_key)

        findings: list[Finding] = []
        seen: set[tuple[str, str, str, str]] = set()
        for (reg_a, name_a, keys_a), (reg_b, name_b, keys_b) in combinations(entries, 2):
            if reg_a == reg_b:
                continue  # inside one combination product: intended
            for record in records:
                forward = record.ingredient_a in keys_a and record.ingredient_b in keys_b
                backward = record.ingredient_b in keys_a and record.ingredient_a in keys_b
                if not (forward or backward):
                    continue
                marker = (reg_a, reg_b, record.ingredient_a, record.ingredient_b)
                if marker in seen:
                    continue
                seen.add(marker)
                findings.append(
                    Finding(
                        "interaction",
                        record.severity.value,
                        (reg_a, reg_b),
                        (name_a, name_b),
                        record.source,
                    )
                )
            if base_key(name_a) and base_key(name_a) == base_key(name_b):
                findings.append(
                    Finding("duplicate_ingredient", None, (reg_a, reg_b), (name_a, name_b), None)
                )

        unmatched = tuple(
            dict.fromkeys(
                (register, name) for register, name, keys in entries if not set(keys) & known
            )
        )
        return InteractionReport(
            findings=tuple(sorted(findings, key=_order)),
            unmatched=unmatched,
            complete=False,
        )


def _order(finding: Finding) -> tuple[int, int, str, str]:
    severity = Severity.from_source(finding.severity or "")
    return (
        _KIND_RANK[finding.kind],
        -severity.rank,
        finding.registers[0],
        finding.registers[1],
    )
