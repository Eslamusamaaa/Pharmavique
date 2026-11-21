"""The saved list as a history: current and past medicines, and only current ones count."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from pharmavique.shared_kernel.events import StoredEvent
from pharmavique.watchlist.application.service import WatchlistService
from pharmavique.watchlist.domain.model import Alert, Allergy, MedicineStatus, SavedMedicine

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Store:
    def __init__(self) -> None:
        self.meds: dict[UUID, dict[str, SavedMedicine]] = {}
        self.alerts_made: list[Alert] = []

    async def add_medicine(self, user_id: UUID, medicine: SavedMedicine) -> bool:
        mine = self.meds.setdefault(user_id, {})
        existing = mine.get(medicine.register_number)
        if existing is not None and existing.status is MedicineStatus.CURRENT:
            return False
        mine[medicine.register_number] = medicine
        return True

    async def set_medicine_status(
        self, user_id: UUID, register_number: str, status: MedicineStatus, at: datetime
    ) -> bool:
        found = self.meds.get(user_id, {}).get(register_number)
        if found is None:
            return False
        self.meds[user_id][register_number] = SavedMedicine(
            register_number, found.added_at, status, at
        )
        return True

    async def remove_medicine(self, user_id: UUID, register_number: str) -> bool:
        return self.meds.get(user_id, {}).pop(register_number, None) is not None

    async def medicines(self, user_id: UUID) -> list[SavedMedicine]:
        return list(self.meds.get(user_id, {}).values())

    async def holders_of(self, register_number: str) -> list[UUID]:
        return [
            u
            for u, m in self.meds.items()
            if register_number in m and m[register_number].status is MedicineStatus.CURRENT
        ]

    async def add_alert(self, alert: Alert) -> bool:
        self.alerts_made.append(alert)
        return True

    async def add_allergy(self, user_id: UUID, allergy: Allergy) -> bool:
        return True

    async def remove_allergy(self, user_id: UUID, key: str) -> bool:
        return True

    async def allergies(self, user_id: UUID) -> list[Allergy]:
        return []

    async def alerts(self, user_id: UUID, unread_only: bool, limit: int) -> list[Alert]:
        return []

    async def unread_count(self, user_id: UUID) -> int:
        return 0

    async def mark_read(self, user_id: UUID, alert_id: UUID | None) -> int:
        return 0

    async def forget(self, user_id: UUID) -> None:
        self.meds.pop(user_id, None)


@pytest.fixture
def store() -> Store:
    return Store()


@pytest.fixture
def service(store: Store) -> WatchlistService:
    return WatchlistService(store, Clock())


async def test_a_saved_medicine_starts_as_current(service: WatchlistService) -> None:
    me = uuid4()
    await service.save_medicine(me, "1-1")
    (saved,) = await service.medicines(me)
    assert saved.status is MedicineStatus.CURRENT


async def test_a_medicine_can_be_marked_past_and_comes_back_as_current(
    service: WatchlistService,
) -> None:
    me = uuid4()
    await service.save_medicine(me, "1-1")

    assert await service.set_status(me, "1-1", MedicineStatus.PAST) is True
    (past,) = await service.medicines(me)
    assert past.status is MedicineStatus.PAST
    assert past.status_changed_at == NOW

    assert await service.save_medicine(me, "1-1") is True  # saving again makes it current
    assert (await service.medicines(me))[0].status is MedicineStatus.CURRENT


async def test_only_current_medicines_are_compared_with_a_new_drug(
    service: WatchlistService,
) -> None:
    me = uuid4()
    for number in ("1-1", "2-2", "3-3"):
        await service.save_medicine(me, number)
    await service.set_status(me, "2-2", MedicineStatus.PAST)

    current = await service.current_medicines(me)
    assert sorted(m.register_number for m in current) == ["1-1", "3-3"]
    assert len(await service.medicines(me)) == 3  # the history keeps all three


async def test_a_status_for_a_medicine_the_person_never_saved_is_refused(
    service: WatchlistService,
) -> None:
    assert await service.set_status(uuid4(), "9-9", MedicineStatus.PAST) is False


async def test_a_past_medicine_raises_no_alert(service: WatchlistService, store: Store) -> None:
    me = uuid4()
    await service.save_medicine(me, "1-1")
    await service.save_medicine(me, "2-2")
    await service.set_status(me, "2-2", MedicineStatus.PAST)

    for number in ("1-1", "2-2"):
        await service.on_event(
            StoredEvent(
                uuid4(),
                "catalog.ProductWithdrawn",
                1,
                NOW,
                {"market": "SA", "register_number": number},
            )
        )

    assert [a.register_number for a in store.alerts_made] == ["1-1"]
