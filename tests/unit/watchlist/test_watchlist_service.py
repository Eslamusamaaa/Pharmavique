"""Saved medicines, allergy matching by name, and alerts made from catalog events."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.events import StoredEvent
from pharmavique.watchlist.application.service import WatchlistService
from pharmavique.watchlist.domain.model import (
    MAX_ALLERGIES,
    Alert,
    AlertKind,
    Allergy,
    MedicineStatus,
    SavedMedicine,
    allergy_matches,
)

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Store:
    def __init__(self) -> None:
        self.meds: dict[UUID, dict[str, SavedMedicine]] = {}
        self.alg: dict[UUID, dict[str, Allergy]] = {}
        self.alert_rows: list[Alert] = []

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
        mine = self.meds.get(user_id, {})
        found = mine.get(register_number)
        if found is None:
            return False
        mine[register_number] = SavedMedicine(register_number, found.added_at, status, at)
        return True

    async def remove_medicine(self, user_id: UUID, register_number: str) -> bool:
        return self.meds.get(user_id, {}).pop(register_number, None) is not None

    async def medicines(self, user_id: UUID) -> list[SavedMedicine]:
        return list(self.meds.get(user_id, {}).values())

    async def add_allergy(self, user_id: UUID, allergy: Allergy) -> bool:
        mine = self.alg.setdefault(user_id, {})
        if allergy.key in mine:
            return False
        mine[allergy.key] = allergy
        return True

    async def remove_allergy(self, user_id: UUID, key: str) -> bool:
        return self.alg.get(user_id, {}).pop(key, None) is not None

    async def allergies(self, user_id: UUID) -> list[Allergy]:
        return list(self.alg.get(user_id, {}).values())

    async def holders_of(self, register_number: str) -> list[UUID]:
        return [
            u
            for u, m in self.meds.items()
            if register_number in m and m[register_number].status is MedicineStatus.CURRENT
        ]

    async def add_alert(self, alert: Alert) -> bool:
        if any(
            a.user_id == alert.user_id and a.event_id == alert.event_id for a in self.alert_rows
        ):
            return False
        self.alert_rows.append(alert)
        return True

    async def alerts(self, user_id: UUID, unread_only: bool, limit: int) -> list[Alert]:
        rows = [a for a in self.alert_rows if a.user_id == user_id]
        return [a for a in rows if not unread_only or a.read_at is None][:limit]

    async def unread_count(self, user_id: UUID) -> int:
        return len(await self.alerts(user_id, True, 1000))

    async def mark_read(self, user_id: UUID, alert_id: UUID | None) -> int:
        return 0

    async def forget(self, user_id: UUID) -> None:
        self.meds.pop(user_id, None)
        self.alg.pop(user_id, None)
        self.alert_rows = [a for a in self.alert_rows if a.user_id != user_id]


def service() -> tuple[WatchlistService, Store]:
    store = Store()
    return WatchlistService(store, Clock()), store


def price_event(register: str = "111", market: str = "SA") -> StoredEvent:
    return StoredEvent(
        uuid4(),
        "catalog.PriceChanged",
        1,
        NOW,
        {
            "market": market,
            "register_number": register,
            "old_price": {
                "amount": "5.00",
                "currency_code": "SAR",
                "currency_basis": "owner_assumption",
            },
            "new_price": {
                "amount": "6.50",
                "currency_code": "SAR",
                "currency_basis": "owner_assumption",
            },
        },
    )


async def test_a_medicine_is_saved_once_and_can_be_removed() -> None:
    svc, _ = service()
    me = uuid4()

    assert await svc.save_medicine(me, " 111 ") is True
    assert await svc.save_medicine(me, "111") is False
    assert [m.register_number for m in await svc.medicines(me)] == ["111"]
    assert await svc.remove_medicine(me, "111") is True
    assert await svc.medicines(me) == []


async def test_one_persons_list_is_not_another_persons() -> None:
    svc, _ = service()
    a, b = uuid4(), uuid4()

    await svc.save_medicine(a, "111")

    assert await svc.medicines(b) == []


async def test_an_allergy_is_recorded_once_by_its_normalized_name() -> None:
    svc, _ = service()
    me = uuid4()

    assert await svc.add_allergy(me, "AMOXICILLIN") is True
    assert await svc.add_allergy(me, "  amoxicillin ") is False
    assert [a.ingredient for a in await svc.allergies(me)] == ["AMOXICILLIN"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
async def test_a_blank_or_huge_ingredient_is_rejected(name: str) -> None:
    svc, _ = service()

    with pytest.raises(InvariantViolation):
        await svc.add_allergy(uuid4(), name)


async def test_the_allergy_list_has_a_limit() -> None:
    svc, _ = service()
    me = uuid4()
    for i in range(MAX_ALLERGIES):
        await svc.add_allergy(me, f"ingredient {i}")

    with pytest.raises(InvariantViolation):
        await svc.add_allergy(me, "one more")


def allergies(*names: str) -> list[Allergy]:
    from pharmavique.watchlist.domain.model import ingredient_key

    return [Allergy(n, ingredient_key(n), NOW) for n in names]


def test_the_same_substance_with_a_salt_word_matches() -> None:
    found = allergy_matches(allergies("AMOXICILLIN"), ["AMOXICILLIN TRIHYDRATE", "CLAVULANIC ACID"])

    assert [(m.allergy, m.ingredient) for m in found] == [("AMOXICILLIN", "AMOXICILLIN TRIHYDRATE")]


def test_a_different_substance_or_a_partial_word_does_not_match() -> None:
    assert allergy_matches(allergies("AMOX"), ["AMOXICILLIN"]) == []
    assert allergy_matches(allergies("PARACETAMOL"), ["IBUPROFEN"]) == []


def test_arabic_and_case_differences_do_not_hide_a_match() -> None:
    assert allergy_matches(allergies("Paracetamol"), ["PARACETAMOL"])
    assert allergy_matches(allergies("باراسيتامول"), ["باراسيتامول"])


async def test_an_event_makes_one_alert_for_each_holder_and_only_for_holders() -> None:
    svc, store = service()
    holder, other = uuid4(), uuid4()
    await svc.save_medicine(holder, "111")
    await svc.save_medicine(other, "222")

    await svc.on_event(price_event("111"))

    assert [(a.user_id, a.kind) for a in store.alert_rows] == [(holder, AlertKind.PRICE_CHANGED)]
    assert store.alert_rows[0].details == {
        "old_price": "5.00",
        "new_price": "6.50",
        "currency_code": "SAR",
        "currency_basis": "owner_assumption",
    }


async def test_a_redelivered_event_adds_no_second_alert() -> None:
    svc, store = service()
    holder = uuid4()
    await svc.save_medicine(holder, "111")
    event = price_event("111")

    await svc.on_event(event)
    await svc.on_event(event)

    assert len(store.alert_rows) == 1


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("catalog.ProductWithdrawn", AlertKind.WITHDRAWN),
        ("catalog.ProductRelisted", AlertKind.RELISTED),
    ],
)
async def test_withdrawn_and_relisted_products_alert_their_holders(
    name: str, kind: AlertKind
) -> None:
    svc, store = service()
    holder = uuid4()
    await svc.save_medicine(holder, "111")

    await svc.on_event(
        StoredEvent(uuid4(), name, 1, NOW, {"market": "SA", "register_number": "111"})
    )

    assert [a.kind for a in store.alert_rows] == [kind]


async def test_other_events_and_other_markets_are_ignored() -> None:
    svc, store = service()
    await svc.save_medicine(uuid4(), "111")

    await svc.on_event(
        StoredEvent(
            uuid4(), "catalog.ProductAdded", 1, NOW, {"market": "SA", "register_number": "111"}
        )
    )
    await svc.on_event(price_event("111", market="EG"))

    assert store.alert_rows == []


async def test_forgetting_a_person_deletes_everything_saved_for_them() -> None:
    svc, store = service()
    me = uuid4()
    await svc.save_medicine(me, "111")
    await svc.add_allergy(me, "AMOXICILLIN")
    await svc.on_event(price_event("111"))

    await svc.forget(me)

    assert await svc.medicines(me) == []
    assert await svc.allergies(me) == []
    assert store.alert_rows == []
