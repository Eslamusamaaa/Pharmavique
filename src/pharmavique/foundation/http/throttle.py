"""Minimum gap between outbound requests, with optional random jitter."""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable


class Throttle:
    def __init__(
        self,
        min_interval: float,
        jitter: float = 0.0,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must not be negative")
        if jitter < 0:
            raise ValueError("jitter must not be negative")
        self._min_interval = min_interval
        self._jitter = jitter
        self._now = now
        self._sleep = sleep
        self._rand = rand
        self._last: float | None = None

    async def wait(self) -> None:
        """Return once at least the configured gap has passed since the previous call."""
        gap = self._min_interval + self._rand() * self._jitter
        if self._last is not None:
            remaining = self._last + gap - self._now()
            if remaining > 0:
                await self._sleep(remaining)
        self._last = self._now()
