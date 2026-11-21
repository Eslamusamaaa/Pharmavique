"""A short-lived, in-memory store for spoken answers, so a phone's audio player can fetch them
by a link. Each entry is served once and expires after a few minutes; nothing is written to disk.

`AudioCache` is one process only; with several API instances use `SharedAudioStore` (below).
"""

import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

from pharmavique.foundation.kv import KeyValueStore, StoreUnavailable


class AudioCache:
    def __init__(
        self,
        ttl_seconds: float = 600.0,
        max_items: int = 200,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_items
        self._now = now
        self._items: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, audio: bytes, media_type: str) -> str:
        key = secrets.token_urlsafe(24)
        with self._lock:
            self._items[key] = (self._now() + self._ttl, audio, media_type)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return key

    def take(self, key: str) -> tuple[bytes, str] | None:
        with self._lock:
            entry = self._items.pop(key, None)
        if entry is None or entry[0] < self._now():
            return None
        return entry[1], entry[2]


class AudioStore(Protocol):
    """Where a spoken answer waits for the phone's audio player to fetch it, once."""

    async def put(self, audio: bytes, media_type: str) -> str: ...

    async def take(self, key: str) -> tuple[bytes, str] | None: ...


class LocalAudioStore:
    """In this process only: right for one API instance."""

    def __init__(self, cache: AudioCache | None = None) -> None:
        self._cache = cache or AudioCache()

    async def put(self, audio: bytes, media_type: str) -> str:
        return self._cache.put(audio, media_type)

    async def take(self, key: str) -> tuple[bytes, str] | None:
        return self._cache.take(key)


class SharedAudioStore:
    """In the shared store, so the player can fetch from any API instance. If the store is down,
    the answer waits in this process instead (it works whenever the same instance is hit)."""

    def __init__(self, store: KeyValueStore, ttl_seconds: int = 600) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self._local = AudioCache(ttl_seconds=float(ttl_seconds))

    async def put(self, audio: bytes, media_type: str) -> str:
        key = secrets.token_urlsafe(24)
        try:
            await self._store.set(f"pv:audio:{key}", media_type.encode() + b"\n" + audio, self._ttl)
        except StoreUnavailable:
            return self._local.put(audio, media_type)
        return key

    async def take(self, key: str) -> tuple[bytes, str] | None:
        try:
            raw = await self._store.getdel(f"pv:audio:{key}")
        except StoreUnavailable:
            return self._local.take(key)
        if raw is None:
            return self._local.take(key)
        media_type, _, audio = raw.partition(b"\n")
        return audio, media_type.decode()
