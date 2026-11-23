"""Polite fetching of one retailer's pages.

robots.txt is honored for every address (including its rules about query strings); one request at
a time with a pause of at least the configured interval and at least the site's own Crawl-delay;
a 401, 403 or 429 ends the run and is never retried; a dropped connection, timeout or 5xx is
retried with a growing wait and then reported as a failed page. A clear User-Agent identifies us.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable

import httpx

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.offers.application.ports import FetchFailed, FetchResult, SourceBlocked
from pharmavique.offers.infrastructure.config import RetailerConfig

__all__ = ["USER_AGENT", "PoliteFetcher"]

USER_AGENT = "DrugRegistrySync/0.1 (polite research crawler; throttled)"
BLOCKED = {401, 403, 429}
_CRAWL_DELAY = re.compile(r"(?im)^\s*crawl-delay\s*:\s*([0-9.]+)")


class PoliteFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        policy: RobotsPolicy | None,
        interval: float,
        *,
        retries: int = 3,
        retry_wait: float = 10.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._policy = policy
        self.interval = interval
        self._retries = retries
        self._retry_wait = retry_wait
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    @classmethod
    async def for_retailer(
        cls, config: RetailerConfig, client: httpx.AsyncClient, **options: object
    ) -> "PoliteFetcher":
        return await cls.for_base(config.base_url, config.min_interval, client, **options)

    @classmethod
    async def for_base(
        cls, base_url: str, min_interval: float, client: httpx.AsyncClient, **options: object
    ) -> "PoliteFetcher":
        """Reads the host's robots.txt first; a missing one (404) allows everything, any other
        failure stops here rather than guess."""
        response = await client.get(base_url + "/robots.txt")
        if response.status_code == 404:
            policy, interval = None, min_interval
        elif response.status_code == 200:
            policy = RobotsPolicy.from_text(response.text, USER_AGENT)
            delays = [float(d) for d in _CRAWL_DELAY.findall(response.text)]
            interval = max([min_interval, *delays])
        else:
            raise SourceBlocked(f"robots.txt answered {response.status_code}")
        return cls(client, policy, interval, **options)  # type: ignore[arg-type]

    async def _pause(self) -> None:
        if self._last is not None:
            wait = self.interval - (self._clock() - self._last)
            if wait > 0:
                await self._sleep(wait)
        self._last = self._clock()

    async def get(self, url: str) -> FetchResult:
        if self._policy is not None and not self._policy.allows(url):
            raise SourceBlocked(f"robots.txt does not allow {url}")
        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            await self._pause()
            try:
                response = await self._client.get(url)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code in BLOCKED:
                    raise SourceBlocked(f"HTTP {response.status_code} for {url}")
                if response.status_code < 500:
                    return FetchResult(
                        response.status_code,
                        response.content,
                        response.headers.get("etag"),
                        response.headers.get("last-modified"),
                        response.headers.get("content-type"),
                    )
                last_error = FetchFailed(f"HTTP {response.status_code}")
            if attempt < self._retries:
                await self._sleep(self._retry_wait * attempt)
        raise FetchFailed(f"{url}: {last_error!r}")
