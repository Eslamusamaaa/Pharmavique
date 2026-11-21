"""The outbox relay: carries integration events from a context's outbox to its subscribers.

Delivery is at least once. A batch is claimed, every subscriber is called for every event, and only
then are the events marked published, so a crash in the middle means the batch is delivered again.
Subscribers must therefore be idempotent (they key their writes on `event_id`). If any subscriber
fails, nothing in the batch is marked published and the error is raised, so nothing is lost; the
relay logs it and tries again on the next round.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from pharmavique.shared_kernel.events import StoredEvent

logger = logging.getLogger("pharmavique.relay")

Subscriber = Callable[[StoredEvent], Awaitable[None]]


class OutboxSource(Protocol):
    async def deliver(self, handler: Subscriber, limit: int) -> int:
        """Claim up to `limit` unpublished events, call `handler` for each in order, mark them
        published when all succeed, and return how many were delivered. The claim and the marking
        happen in one transaction; a handler error aborts it and propagates."""
        ...


class OutboxRelay:
    def __init__(self, sources: Sequence[OutboxSource], subscribers: Sequence[Subscriber]) -> None:
        self._sources = list(sources)
        self._subscribers = list(subscribers)

    async def _dispatch(self, event: StoredEvent) -> None:
        for subscriber in self._subscribers:
            await subscriber(event)

    async def run_once(self, batch: int = 200) -> int:
        """Deliver one batch from every source. Returns the number of events delivered."""
        total = 0
        for source in self._sources:
            total += await source.deliver(self._dispatch, batch)
        return total

    async def run_until_empty(self, batch: int = 200) -> int:
        total = 0
        while delivered := await self.run_once(batch):
            total += delivered
        return total

    async def run_forever(self, interval_seconds: float = 5.0, batch: int = 200) -> None:
        while True:
            try:
                if await self.run_once(batch):
                    continue  # more may be waiting: go again without sleeping
            except Exception:
                logger.exception("outbox relay round failed; trying again")
            await asyncio.sleep(interval_seconds)
