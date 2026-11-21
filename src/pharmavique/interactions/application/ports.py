from collections.abc import Collection
from typing import Protocol

from pharmavique.interactions.domain.records import ContraindicationRecord, InteractionRecord


class InteractionStore(Protocol):
    async def known(self, keys: Collection[str]) -> set[str]:
        """Which of these keys the source has any record for (as either side of a pair)."""
        ...

    async def pairs_among(self, keys: Collection[str]) -> list[InteractionRecord]:
        """Every recorded pair whose two ingredients are both among `keys`."""
        ...


class ContraindicationStore(Protocol):
    async def for_ingredients(self, keys: Collection[str]) -> list[ContraindicationRecord]:
        """Every record whose ingredient key is among `keys`."""
        ...
