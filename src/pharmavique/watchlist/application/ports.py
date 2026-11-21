"""What the watchlist use cases need from storage. Every per-person call names the person."""

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pharmavique.watchlist.domain.model import Alert, Allergy, MedicineStatus, SavedMedicine


class WatchlistStore(Protocol):
    async def add_medicine(self, user_id: UUID, medicine: SavedMedicine) -> bool:
        """False when the medicine was already saved as a current one. Saving a past medicine
        again makes it current."""
        ...

    async def set_medicine_status(
        self, user_id: UUID, register_number: str, status: MedicineStatus, at: datetime
    ) -> bool:
        """False when the person has not saved this medicine."""
        ...

    async def remove_medicine(self, user_id: UUID, register_number: str) -> bool: ...

    async def medicines(self, user_id: UUID) -> list[SavedMedicine]: ...

    async def add_allergy(self, user_id: UUID, allergy: Allergy) -> bool:
        """False when the allergy was already recorded."""
        ...

    async def remove_allergy(self, user_id: UUID, key: str) -> bool: ...

    async def allergies(self, user_id: UUID) -> list[Allergy]: ...

    async def holders_of(self, register_number: str) -> list[UUID]:
        """Everyone who currently takes this medicine (a past one raises no alert). For event
        handlers only, never for an API caller."""
        ...

    async def add_alert(self, alert: Alert) -> bool:
        """False when this person already has an alert for this event."""
        ...

    async def alerts(self, user_id: UUID, unread_only: bool, limit: int) -> list[Alert]: ...

    async def unread_count(self, user_id: UUID) -> int: ...

    async def mark_read(self, user_id: UUID, alert_id: UUID | None) -> int:
        """Mark one alert read, or every alert of the person when `alert_id` is None."""
        ...

    async def forget(self, user_id: UUID) -> None:
        """Delete everything saved for the person."""
        ...


class AlertEmailStore(Protocol):
    """Alerts the email digest has not handled yet. For the digest job only: it sees everyone."""

    async def pending_email_alerts(self, limit: int) -> list[Alert]:
        """Unread alerts nobody has emailed or skipped yet, oldest first."""
        ...

    async def mark_emailed(self, alert_ids: Iterable[UUID], at: datetime) -> None: ...
