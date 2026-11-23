"""What the crawl needs from the outside world. Implemented in `infrastructure`."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pharmavique.offers.domain.model import JobType, ListingCategory, RunStatus
from pharmavique.offers.domain.page import ParsedProduct


class SourceBlocked(Exception):
    """A 401, 403 or 429, or a robots.txt refusal: the run for this site ends, no retry."""


class FetchFailed(Exception):
    """The page could not be read after the retries (network error, 5xx)."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    status: int
    content: bytes
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    url: str
    lastmod: str | None = None


@dataclass(frozen=True, slots=True)
class SaveResult:
    new: bool
    price_changed: bool
    details_changed: bool
    quarantined: bool  # a price that looked wrong was held back


class PageFetcher(Protocol):
    async def get(self, url: str) -> FetchResult: ...


class SitemapSource(Protocol):
    async def entries(self) -> list[SitemapEntry]: ...


class ListingStore(Protocol):
    async def ensure_retailer(self) -> None: ...

    async def known_urls(self) -> set[str]:
        """Every address already stored or already judged not to be a product."""
        ...

    async def save(
        self, product: ParsedProduct, category: ListingCategory, now: datetime
    ) -> SaveResult: ...

    async def skip(self, url: str, reason: str, now: datetime) -> None: ...

    async def start_run(self, job: JobType, now: datetime) -> int: ...

    async def finish_run(
        self, run_id: int, status: RunStatus, counters: dict[str, int], now: datetime
    ) -> None: ...
