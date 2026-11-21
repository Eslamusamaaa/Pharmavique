"""A small shared key-value store: the one place the API instances keep state they must share.

Behind several API instances anything held in a process (rate-limit counts, the read cache, spoken
audio links) is wrong or wasted, so it lives here. `RedisStore` is the real one; `MemoryStore` is
for tests and for running a single process without Redis. Every method either works or raises
`StoreUnavailable`; callers decide how to degrade (the cache serves from the database, the rate
limit falls back to a per-process count) and never let a store outage fail a request.
"""

import math
import time
from collections.abc import Callable
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError


def redis_client(url: str, *, timeout: float) -> Redis:
    """A Redis client with short timeouts. `localhost` is turned into 127.0.0.1: on Windows the name
    resolves to the IPv6 address first and every new connection then waits about two seconds."""
    return Redis.from_url(
        url.replace("://localhost:", "://127.0.0.1:", 1),
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
        health_check_interval=30,
    )


class StoreUnavailable(Exception):
    """The store could not be reached in time."""


class KeyValueStore(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...

    async def getdel(self, key: str) -> bytes | None:
        """Read and delete in one step, so a value can be handed out once."""
        ...

    async def delete(self, key: str) -> None: ...

    async def bump(self, key: str) -> int:
        """Add one to a counter that never expires and return the new value."""
        ...

    async def window_hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Count one hit in a fixed window: (hits so far, seconds until the window ends)."""
        ...


class RedisStore:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get(self, key: str) -> bytes | None:
        try:
            value: bytes | None = await self._client.get(key)
        except (RedisError, OSError, TimeoutError) as error:
            raise StoreUnavailable(str(error)) from error
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        try:
            await self._client.set(key, value, ex=ttl_seconds)
        except (RedisError, OSError, TimeoutError) as error:
            raise StoreUnavailable(str(error)) from error

    async def getdel(self, key: str) -> bytes | None:
        try:
            value: bytes | None = await self._client.getdel(key)
        except (RedisError, OSError, TimeoutError) as error:
            raise StoreUnavailable(str(error)) from error
        return value

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except (RedisError, OSError, TimeoutError) as error:
            raise StoreUnavailable(str(error)) from error

    async def bump(self, key: str) -> int:
        try:
            return int(await self._client.incr(key))
        except (RedisError, OSError, TimeoutError) as error:
            raise StoreUnavailable(str(error)) from error

    async def window_hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        try:
            # one round trip; EXPIRE ... NX sets the window only on the first hit
            pipe = self._client.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()
        except (RedisError, OSError, TimeoutError) as error:
            raise StoreUnavailable(str(error)) from error
        return int(count), max(1, int(ttl)) if int(ttl) > 0 else window_seconds

    async def close(self) -> None:
        await self._client.aclose()


class MemoryStore:
    """In-process stand-in with the same behaviour, including expiry."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._values: dict[str, tuple[bytes, float | None]] = {}
        self.down = False  # tests flip this to simulate an outage

    def _check(self) -> None:
        if self.down:
            raise StoreUnavailable("memory store switched off")

    def _live(self, key: str) -> bytes | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires is not None and expires <= self._clock():
            del self._values[key]
            return None
        return value

    async def get(self, key: str) -> bytes | None:
        self._check()
        return self._live(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        self._check()
        self._values[key] = (value, self._clock() + ttl_seconds)

    async def getdel(self, key: str) -> bytes | None:
        self._check()
        value = self._live(key)
        self._values.pop(key, None)
        return value

    async def delete(self, key: str) -> None:
        self._check()
        self._values.pop(key, None)

    async def bump(self, key: str) -> int:
        self._check()
        current = int(self._live(key) or b"0") + 1
        self._values[key] = (str(current).encode(), None)
        return current

    async def window_hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        self._check()
        now = self._clock()
        entry = self._values.get(key)
        if entry is None or (entry[1] is not None and entry[1] <= now):
            self._values[key] = (b"1", now + window_seconds)
            return 1, window_seconds
        count = int(entry[0]) + 1
        self._values[key] = (str(count).encode(), entry[1])
        return count, max(1, math.ceil((entry[1] or now) - now))
