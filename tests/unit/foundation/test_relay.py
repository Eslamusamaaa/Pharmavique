"""The relay delivers each event to every subscriber and stops cleanly when a subscriber fails."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from pharmavique.foundation.events.relay import OutboxRelay, Subscriber
from pharmavique.shared_kernel.events import StoredEvent


def event(name: str = "catalog.PriceChanged") -> StoredEvent:
    return StoredEvent(
        uuid4(), name, 1, datetime(2026, 11, 21, tzinfo=UTC), {"register_number": "1"}
    )


class FakeSource:
    """Like the Postgres source: a failing handler leaves every event of the batch unpublished."""

    def __init__(self, events: list[StoredEvent]) -> None:
        self.waiting = list(events)
        self.published: list[StoredEvent] = []

    async def deliver(self, handler: Subscriber, limit: int) -> int:
        batch = self.waiting[:limit]
        for item in batch:
            await handler(item)
        self.waiting = self.waiting[len(batch) :]
        self.published.extend(batch)
        return len(batch)


async def test_every_subscriber_sees_every_event_in_order() -> None:
    first, second = event(), event("catalog.ProductWithdrawn")
    source = FakeSource([first, second])
    seen_a: list[StoredEvent] = []
    seen_b: list[StoredEvent] = []

    async def a(item: StoredEvent) -> None:
        seen_a.append(item)

    async def b(item: StoredEvent) -> None:
        seen_b.append(item)

    delivered = await OutboxRelay([source], [a, b]).run_once()

    assert delivered == 2
    assert seen_a == seen_b == [first, second]
    assert source.waiting == []


async def test_run_until_empty_works_through_several_batches() -> None:
    source = FakeSource([event() for _ in range(5)])

    async def ignore(item: StoredEvent) -> None:
        return None

    total = await OutboxRelay([source], [ignore]).run_until_empty(batch=2)

    assert total == 5
    assert len(source.published) == 5


async def test_a_failing_subscriber_leaves_the_batch_waiting_and_raises() -> None:
    source = FakeSource([event()])

    async def broken(item: StoredEvent) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await OutboxRelay([source], [broken]).run_once()

    assert len(source.waiting) == 1
    assert source.published == []


async def test_with_nothing_waiting_nothing_is_delivered() -> None:
    async def ignore(item: StoredEvent) -> None:
        return None

    assert await OutboxRelay([FakeSource([])], [ignore]).run_once() == 0
