"""Polite fetching shared by the SFDA crawlers.

Every URL is checked against robots.txt first; HTTP 401/403/429 stop the crawl at once; network
errors, timeouts, 5xx answers and pages that do not parse are retried with a growing wait; a page
that never parses is never returned, so a block page cannot become "data".
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import FetchedPage, PageFetcher
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import (
    FetchFailed,
    NotFound,
    SourceBlocked,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import ParseError

_log = logging.getLogger("sfda.fetch")


class PoliteFetch:
    def __init__(
        self,
        fetcher: PageFetcher,
        robots: RobotsPolicy,
        *,
        retries: int,
        retry_wait: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._fetcher = fetcher
        self._robots = robots
        self._retries = retries
        self._retry_wait = retry_wait
        self._sleep = sleep

    async def fetch_valid[T](self, url: str, parse: Callable[[str], T]) -> tuple[FetchedPage, T]:
        if not self._robots.allows(url):
            raise SourceBlocked(f"robots.txt does not allow {url}")

        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                page = await self._fetcher.fetch(url)
            except Exception as exc:  # network errors and timeouts are retried
                last_error = exc
            else:
                if page.status in (401, 403, 429):
                    raise SourceBlocked(f"HTTP {page.status} for {url}")
                if page.status == 404:
                    raise NotFound(f"HTTP 404 for {url}")
                if page.status == 200:
                    try:
                        return page, parse(page.html)
                    except ParseError as exc:
                        last_error = exc
                else:
                    last_error = FetchFailed(f"HTTP {page.status}")
            if attempt < self._retries:
                wait = self._retry_wait * attempt
                _log.warning(
                    "attempt %s of %s failed for %s (%s); waiting %.0f s",
                    attempt,
                    self._retries,
                    url,
                    last_error,
                    wait,
                )
                await self._sleep(wait)
        raise FetchFailed(f"{url}: {last_error}")
