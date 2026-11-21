"""The shelf list service: confirmations are validated and capped."""

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.watchlist.application.shelf import ShelfService
from pharmavique.watchlist.domain.model import MAX_SHELF, ShelfItem

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Store:
    def __init__(self) -> None:
        self.items: dict[UUID, dict[str, datetime]] = {}

    async def add_shelf_items(
        self, user_id: UUID, register_numbers: Iterable[str], at: datetime
    ) -> int:
        mine = self.items.setdefault(user_id, {})
        added = 0
        for number in register_numbers:
            if number not in mine:
                mine[number] = at
                added += 1
        return added

    async def remove_shelf_item(self, user_id: UUID, register_number: str) -> bool:
        return self.items.get(user_id, {}).pop(register_number, None) is not None

    async def shelf(self, user_id: UUID) -> list[ShelfItem]:
        return [ShelfItem(r, t) for r, t in self.items.get(user_id, {}).items()]


@pytest.fixture
def service() -> ShelfService:
    return ShelfService(Store(), Clock())


async def test_confirming_adds_each_medicine_once(service: ShelfService) -> None:
    me = uuid4()
    assert await service.confirm(me, ["1", "2", "1", " 2 "]) == 2
    assert await service.confirm(me, ["2", "3"]) == 1
    assert sorted(i.register_number for i in await service.items(me)) == ["1", "2", "3"]


async def test_confirming_nothing_is_refused(service: ShelfService) -> None:
    with pytest.raises(InvariantViolation):
        await service.confirm(uuid4(), ["", "  "])


async def test_the_list_has_a_limit(service: ShelfService) -> None:
    me = uuid4()
    await service.confirm(me, [str(i) for i in range(MAX_SHELF)])
    with pytest.raises(InvariantViolation):
        await service.confirm(me, ["one-more"])


async def test_a_medicine_can_be_removed_once(service: ShelfService) -> None:
    me = uuid4()
    await service.confirm(me, ["1"])
    assert await service.remove(me, "1") is True
    assert await service.remove(me, "1") is False
