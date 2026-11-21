"""Request limits per client address, so one caller cannot exhaust the API or the AI budget.

Two windows of one minute: a general one, and a lower one for the endpoints that cost money or
CPU (assistant, voice, scan). When a shared store is available the counts live there, so the
limit holds across every API instance; if the store is down each instance falls back to counting
for itself (a limit that is too loose for a moment, never an outage). Behind a load balancer the
client address is read from X-Forwarded-For, trusting only the entry our own balancer appended.
"""

import math
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from pharmavique.foundation.kv import KeyValueStore, StoreUnavailable

HEAVY_PREFIXES = ("/v1/assistant", "/v1/voice", "/v1/recognition", "/v1/auth")
HEAVY_WHEN_POSTING = ("/v1/jobs",)  # submitting is heavy; polling a job is cheap and frequent
EXEMPT_PATHS = frozenset({"/health", "/ready"})
_SWEEP_EVERY = 256  # requests between clean-ups of idle clients


class SlidingWindow:
    """At most `limit` requests per client in any `seconds`."""

    def __init__(
        self, limit: int, seconds: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._seconds = seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._calls = 0

    def allow(self, client: str) -> bool:
        now = self._clock()
        self._calls += 1
        if self._calls % _SWEEP_EVERY == 0 or len(self._hits) > 10_000:
            self._sweep(now)
        hits = self._hits[client]
        self._expire(hits, now)
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def retry_after(self, client: str) -> int:
        hits = self._hits.get(client)
        if not hits:
            return 0
        return max(1, math.ceil(hits[0] + self._seconds - self._clock()))

    def tracked(self) -> int:
        self._sweep(self._clock())
        return len(self._hits)

    def _expire(self, hits: deque[float], now: float) -> None:
        while hits and hits[0] <= now - self._seconds:
            hits.popleft()

    def _sweep(self, now: float) -> None:
        for client in list(self._hits):
            self._expire(self._hits[client], now)
            if not self._hits[client]:
                del self._hits[client]


def client_address(request: Request, trusted_proxy_hops: int) -> str:
    """The caller's address. With `trusted_proxy_hops` = n, the n-th entry from the right of
    X-Forwarded-For (the one our own balancer appended); entries further left can be forged."""
    if trusted_proxy_hops > 0:
        forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")]
        forwarded = [p for p in forwarded if p]
        if len(forwarded) >= trusted_proxy_hops:
            return forwarded[-trusted_proxy_hops]
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: object,
        *,
        general: int,
        heavy: int,
        store: Callable[[], KeyValueStore | None] | None = None,
        trusted_proxy_hops: int = 0,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._general = SlidingWindow(general) if general > 0 else None
        self._heavy = SlidingWindow(heavy) if heavy > 0 else None
        self._limits = {"general": general, "heavy": heavy}
        self._store = store
        self._hops = trusted_proxy_hops

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        client = client_address(request, self._hops)
        if path not in EXEMPT_PATHS:
            for scope, window in self._windows(path, request.method):
                wait = await self._check(scope, window, client)
                if wait is not None:
                    return JSONResponse(
                        {"detail": "too many requests, try again shortly"},
                        status_code=429,
                        headers={"Retry-After": str(wait)},
                    )
        return await call_next(request)

    async def _check(self, scope: str, window: SlidingWindow, client: str) -> int | None:
        """None when allowed, else the seconds to wait."""
        store = self._store() if self._store is not None else None
        if store is not None:
            try:
                count, left = await store.window_hit(f"pv:rl:{scope}:{client}", 60)
            except StoreUnavailable:
                pass  # fall back to this process's own count below
            else:
                return None if count <= self._limits[scope] else left
        if window.allow(client):
            return None
        return window.retry_after(client)

    def _windows(self, path: str, method: str) -> list[tuple[str, SlidingWindow]]:
        windows = [("general", self._general)] if self._general is not None else []
        heavy = path.startswith(HEAVY_PREFIXES) or (
            method == "POST" and path.startswith(HEAVY_WHEN_POSTING)
        )
        if self._heavy is not None and heavy:
            windows.append(("heavy", self._heavy))
        return windows
