"""Saved medicines, allergies and alerts, and the handler that turns catalog events into alerts.

An alert says what changed in the registry (a price, a withdrawal) and nothing about what to do.
Events arrive at least once, so the handler is idempotent: a person gets one alert per event.
"""

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID, uuid4

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.events import StoredEvent
from pharmavique.shared_kernel.ports import Clock
from pharmavique.watchlist.application.ports import WatchlistStore
from pharmavique.watchlist.domain.model import (
    MAX_ALLERGIES,
    MAX_MEDICINES,
    Alert,
    AlertKind,
    Allergy,
    AllergyMatch,
    MedicineStatus,
    SavedMedicine,
    allergy_matches,
    ingredient_key,
)

_MARKET = "SA"
_KINDS = {
    "catalog.PriceChanged": AlertKind.PRICE_CHANGED,
    "catalog.ProductWithdrawn": AlertKind.WITHDRAWN,
    "catalog.ProductRelisted": AlertKind.RELISTED,
}


def _price_text(price: Mapping[str, Any] | None) -> str | None:
    if not price:
        return None
    return str(price.get("amount"))


def _details(event: StoredEvent) -> dict[str, str | None]:
    if event.event_type != "catalog.PriceChanged":
        return {}
    old, new = event.payload.get("old_price"), event.payload.get("new_price")
    shown = new or old or {}
    return {
        "old_price": _price_text(old),
        "new_price": _price_text(new),
        "currency_code": shown.get("currency_code"),
        "currency_basis": shown.get("currency_basis"),
    }


class WatchlistService:
    def __init__(self, store: WatchlistStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    # ---- saved medicines ------------------------------------------------------------------
    async def save_medicine(self, user_id: UUID, register_number: str) -> bool:
        number = register_number.strip()
        if not number or len(number) > 40:
            raise InvariantViolation("enter a register number")
        if len(await self._store.medicines(user_id)) >= MAX_MEDICINES:
            raise InvariantViolation(f"the list holds at most {MAX_MEDICINES} medicines")
        return await self._store.add_medicine(user_id, SavedMedicine(number, self._clock.now()))

    async def set_status(self, user_id: UUID, register_number: str, status: MedicineStatus) -> bool:
        return await self._store.set_medicine_status(
            user_id, register_number.strip(), status, self._clock.now()
        )

    async def current_medicines(self, user_id: UUID) -> list[SavedMedicine]:
        """What the person takes now: the only medicines a new drug is compared with."""
        return [
            m for m in await self._store.medicines(user_id) if m.status is MedicineStatus.CURRENT
        ]

    async def remove_medicine(self, user_id: UUID, register_number: str) -> bool:
        return await self._store.remove_medicine(user_id, register_number.strip())

    async def medicines(self, user_id: UUID) -> list[SavedMedicine]:
        return await self._store.medicines(user_id)

    # ---- allergies ------------------------------------------------------------------------
    async def add_allergy(self, user_id: UUID, ingredient: str) -> bool:
        key = ingredient_key(ingredient)
        if len(await self._store.allergies(user_id)) >= MAX_ALLERGIES:
            raise InvariantViolation(f"at most {MAX_ALLERGIES} allergies can be recorded")
        return await self._store.add_allergy(
            user_id, Allergy(ingredient.strip(), key, self._clock.now())
        )

    async def remove_allergy(self, user_id: UUID, ingredient: str) -> bool:
        return await self._store.remove_allergy(user_id, ingredient_key(ingredient))

    async def allergies(self, user_id: UUID) -> list[Allergy]:
        return await self._store.allergies(user_id)

    async def check_allergies(
        self, user_id: UUID, ingredient_names: Iterable[str]
    ) -> list[AllergyMatch]:
        return allergy_matches(await self._store.allergies(user_id), ingredient_names)

    # ---- alerts ---------------------------------------------------------------------------
    async def alerts(
        self, user_id: UUID, unread_only: bool = False, limit: int = 50
    ) -> list[Alert]:
        return await self._store.alerts(user_id, unread_only, limit)

    async def unread_count(self, user_id: UUID) -> int:
        return await self._store.unread_count(user_id)

    async def mark_read(self, user_id: UUID, alert_id: UUID | None) -> int:
        return await self._store.mark_read(user_id, alert_id)

    async def forget(self, user_id: UUID) -> None:
        await self._store.forget(user_id)

    # ---- events ---------------------------------------------------------------------------
    async def on_event(self, event: StoredEvent) -> None:
        """Make an alert for everyone who saved the product the event is about."""
        kind = _KINDS.get(event.event_type)
        if kind is None or event.payload.get("market") != _MARKET:
            return
        register_number = str(event.payload["register_number"])
        details = _details(event)
        for user_id in await self._store.holders_of(register_number):
            await self._store.add_alert(
                Alert(
                    id=uuid4(),
                    user_id=user_id,
                    kind=kind,
                    register_number=register_number,
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                    details=details,
                    created_at=self._clock.now(),
                    read_at=None,
                )
            )
