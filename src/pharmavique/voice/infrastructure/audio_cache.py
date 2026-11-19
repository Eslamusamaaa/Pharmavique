"""A short-lived, in-memory store for spoken answers, so a phone's audio player can fetch them
by a link. Each entry is served once and expires after a few minutes; nothing is written to disk.

One process only: with several API processes this moves to Redis (ADR-002).
"""

import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable


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
