"""Outbox writer: integration events are stored in the same transaction as the state change."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.infrastructure.persistence.models import OutboxRow
from pharmavique.foundation.events.payload import event_payload
from pharmavique.foundation.events.relay import Subscriber
from pharmavique.shared_kernel.events import IntegrationEvent, StoredEvent

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


class SqlAlchemyOutboxPublisher:
    """Reads the catalog's unpublished events for the relay, in the order they happened."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def deliver(self, handler: Subscriber, limit: int) -> int:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        select(OutboxRow)
                        .where(OutboxRow.published_at.is_(None))
                        .order_by(OutboxRow.occurred_at, OutboxRow.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                await handler(
                    StoredEvent(
                        event_id=row.id,
                        event_type=row.event_type,
                        schema_version=row.schema_version,
                        occurred_at=row.occurred_at,
                        payload=row.payload,
                    )
                )
            now = datetime.now(UTC)
            for row in rows:
                row.published_at = now
            return len(rows)
