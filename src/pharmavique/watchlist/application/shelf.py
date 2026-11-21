"""A pharmacist's shelf list: medicines they confirmed after scanning a shelf.

The scan only proposes (every box needs review); a medicine reaches the list when the pharmacist
confirms it. The list says which medicines they shelve, not how many and not whether they are in
stock. It raises the same alerts as a saved medicine (a price change, a withdrawal).
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.ports import Clock
from pharmavique.watchlist.domain.model import MAX_SHELF, ShelfItem


class ShelfStore(Protocol):
    async def add_shelf_items(
        self, user_id: UUID, register_numbers: Iterable[str], at: datetime
    ) -> int:
        """Add the medicines that are not on the shelf yet; the number added."""
        ...

    async def remove_shelf_item(self, user_id: UUID, register_number: str) -> bool: ...

    async def shelf(self, user_id: UUID) -> list[ShelfItem]: ...


class ShelfService:
    def __init__(self, store: ShelfStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    async def confirm(self, user_id: UUID, register_numbers: Iterable[str]) -> int:
        wanted = list(dict.fromkeys(r.strip() for r in register_numbers if r.strip()))
        if not wanted:
            raise InvariantViolation("confirm at least one medicine")
        if len(await self._store.shelf(user_id)) + len(wanted) > MAX_SHELF:
            raise InvariantViolation(f"the shelf list holds at most {MAX_SHELF} medicines")
        return await self._store.add_shelf_items(user_id, wanted, self._clock.now())

    async def remove(self, user_id: UUID, register_number: str) -> bool:
        return await self._store.remove_shelf_item(user_id, register_number.strip())

    async def items(self, user_id: UUID) -> list[ShelfItem]:
        return await self._store.shelf(user_id)
