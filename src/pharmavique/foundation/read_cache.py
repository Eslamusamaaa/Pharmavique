"""A read cache for public answers (search, drug pages), shared by every API instance.

Keys carry a data version. Anything that changes what the API would answer (a catalog load, a search
reindex, a relayed catalog event) bumps the version, so every older entry is simply never read
again and expires on its own. A short in-process copy of the version keeps the hot path to one store
read; other instances notice a bump within `version_cache_seconds`.

Safe to lose: if the store is down the answer is computed from the database and nothing fails.
One computation per key runs at a time in a process, so a popular entry expiring does not send a
crowd to the database. Only answers that were computed successfully are stored (never a 404 or
an error).
"""

import asyncio
import contextlib
import hashlib
import random
import time
from collections.abc import Awaitable, Callable, Sequence

from pharmavique.foundation.kv import KeyValueStore, StoreUnavailable

VERSION_KEY = "pv:data_version"
Observer = Callable[[str, str], None]  # (namespace, "hit" | "miss" | "error")


class ReadCache:
    def __init__(
        self,
        store: KeyValueStore,
        *,
        ttl_seconds: int = 600,
        version_cache_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        observer: Observer | None = None,
    ) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self._version_ttl = version_cache_seconds
        self._clock = clock
        self._observer = observer
        self._version: str | None = None
        self._version_at = 0.0
        self._inflight: dict[str, asyncio.Task[bytes]] = {}

    def _note(self, namespace: str, result: str) -> None:
        if self._observer is not None:
            self._observer(namespace, result)

    async def _current_version(self) -> str:
        now = self._clock()
        if self._version is not None and now - self._version_at < self._version_ttl:
            return self._version
        raw = await self._store.get(VERSION_KEY)
        self._version = raw.decode() if raw else "0"
        self._version_at = now
        return self._version

    async def invalidate_all(self) -> None:
        """Make every stored entry unreadable (call after the data changed)."""
        self._version = str(await self._store.bump(VERSION_KEY))
        self._version_at = self._clock()

    @staticmethod
    def _key(version: str, namespace: str, parts: Sequence[str]) -> str:
        digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]
        return f"pv:c:{version}:{namespace}:{digest}"

    async def fetch(
        self,
        namespace: str,
        parts: Sequence[str],
        compute: Callable[[], Awaitable[bytes]],
    ) -> tuple[bytes, bool]:
        """The cached bytes for this request and whether they came from the cache."""
        try:
            key = self._key(await self._current_version(), namespace, parts)
            cached = await self._store.get(key)
        except StoreUnavailable:
            self._note(namespace, "error")
            return await compute(), False
        if cached is not None:
            self._note(namespace, "hit")
            return cached, True
        self._note(namespace, "miss")

        pending = self._inflight.get(key)
        if pending is None:
            pending = asyncio.ensure_future(self._fill(key, compute))
            self._inflight[key] = pending
            pending.add_done_callback(lambda _: self._inflight.pop(key, None))
        return await asyncio.shield(pending), False

    async def _fill(self, key: str, compute: Callable[[], Awaitable[bytes]]) -> bytes:
        value = await compute()
        ttl = max(1, int(self._ttl * random.uniform(0.9, 1.1)))  # noqa: S311 - spreads expiries
        with contextlib.suppress(StoreUnavailable):  # the answer is still good, just not stored
            await self._store.set(key, value, ttl)
        return value
