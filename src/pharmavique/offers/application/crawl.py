"""The first full load of one retailer: every product address in its sitemaps, once.

Resumable by construction: an address already stored (or already judged not to be a product) is
never fetched again, so a stopped run continues where it stopped. A block ends the run at once;
a failed page makes the run `partial`; the run is `complete` only when every address was dealt
with.
"""

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from pharmavique.offers.application.ports import (
    FetchFailed,
    ListingStore,
    PageFetcher,
    SitemapSource,
    SourceBlocked,
)
from pharmavique.offers.domain.category import classify
from pharmavique.offers.domain.lifecycle import RunOutcome, classify_run
from pharmavique.offers.domain.model import JobType, RunStatus
from pharmavique.offers.domain.page import ParsedProduct

__all__ = ["CrawlBudget", "CrawlReport", "InitialLoad"]

GONE = {404, 410}


@dataclass(frozen=True, slots=True)
class CrawlBudget:
    limit: int | None = None  # at most this many addresses in this run
    max_seconds: float | None = None  # stop starting new pages after this long


@dataclass(slots=True)
class CrawlReport:
    status: RunStatus
    counters: dict[str, int] = field(default_factory=dict)


def _text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


class InitialLoad:
    def __init__(
        self,
        sitemap: SitemapSource,
        fetcher: PageFetcher,
        store: ListingStore,
        parse: Callable[[str, str], ParsedProduct | None],
        now: Callable[[], datetime],
        decode: Callable[[bytes], str] = _text,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sitemap = sitemap
        self._fetcher = fetcher
        self._store = store
        self._parse = parse
        self._now = now
        self._decode = decode
        self._clock = clock

    async def run(self, budget: CrawlBudget) -> CrawlReport:
        await self._store.ensure_retailer()
        run_id = await self._store.start_run(JobType.DISCOVER, self._now())
        entries = await self._sitemap.entries()
        known = await self._store.known_urls()
        todo = [e.url for e in entries if e.url not in known]
        counts: Counter[str] = Counter(discovered=len(entries), known=len(entries) - len(todo))
        started = self._clock()
        blocked = False
        done = 0
        for url in todo:
            if budget.limit is not None and done >= budget.limit:
                break
            if budget.max_seconds is not None and self._clock() - started >= budget.max_seconds:
                break
            try:
                await self._one(url, counts)
            except SourceBlocked:
                blocked = True
                break
            except FetchFailed:
                counts["failed"] += 1
            done += 1
        remaining = len(todo) - done
        counts["remaining"] = remaining
        status = classify_run(
            RunOutcome(
                enumeration_finished=remaining == 0 and not blocked and bool(entries),
                blocked=blocked,
                unhandled_errors=counts["failed"],
                urls_seen=len(entries),
            ),
            None,
        )
        counters = dict(counts)
        await self._store.finish_run(run_id, status, counters, self._now())
        return CrawlReport(status, counters)

    async def _one(self, url: str, counts: Counter[str]) -> None:
        counts["requests"] += 1
        result = await self._fetcher.get(url)
        if result.status in GONE:
            await self._store.skip(url, "gone", self._now())
            counts["skipped"] += 1
            return
        if result.status != 200:
            raise FetchFailed(f"HTTP {result.status}")
        product = self._parse(self._decode(result.content), url)
        if product is None:
            await self._store.skip(url, "not_a_product", self._now())
            counts["skipped"] += 1
            return
        category = classify(product.category_path)
        saved = await self._store.save(product, category, self._now())
        counts[
            "new"
            if saved.new
            else "changed"
            if saved.price_changed or saved.details_changed
            else "unchanged"
        ] += 1
        counts[f"category_{category.value}"] += 1
        if product.price is None:
            counts["missing_price"] += 1
        if saved.quarantined:
            counts["quarantined"] += 1
