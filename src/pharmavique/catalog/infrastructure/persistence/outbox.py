"""Outbox writer: integration events are stored in the same transaction as the state change."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from pharmavique.catalog.infrastructure.persistence.models import OutboxRow
from pharmavique.foundation.events.payload import event_payload
from pharmavique.shared_kernel.events import IntegrationEvent

_CONTEXT = "catalog"


class SqlAlchemyOutbox:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, events: Sequence[IntegrationEvent]) -> None:
        self._session.add_all(
            OutboxRow(
                id=event.event_id,
                event_type=f"{_CONTEXT}.{type(event).__name__}",
                schema_version=event.schema_version,
                occurred_at=event.occurred_at,
                payload=event_payload(event),
                published_at=None,
            )
            for event in events
        )
        await self._session.flush()
