"""Request limits per client address, so one caller cannot exhaust the API or the AI budget.

Two windows of one minute: a general one, and a lower one for the endpoints that cost money or
CPU (assistant, voice, scan). The counts live in this process, which is enough for one API
instance; behind several instances the same rule moves to Redis (ADR-004, step 6).
"""

import math
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

HEAVY_PREFIXES = ("/v1/assistant", "/v1/voice", "/v1/recognition", "/v1/auth")
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


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, general: int, heavy: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._general = SlidingWindow(general) if general > 0 else None
        self._heavy = SlidingWindow(heavy) if heavy > 0 else None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        client = request.client.host if request.client else "unknown"
        if path not in EXEMPT_PATHS:
            for window in self._windows(path):
                if not window.allow(client):
                    return JSONResponse(
                        {"detail": "too many requests, try again shortly"},
                        status_code=429,
                        headers={"Retry-After": str(window.retry_after(client))},
                    )
        return await call_next(request)

    def _windows(self, path: str) -> list[SlidingWindow]:
        windows = [self._general] if self._general is not None else []
        if self._heavy is not None and path.startswith(HEAVY_PREFIXES):
            windows.append(self._heavy)
        return windows
