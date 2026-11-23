"""The initial load of one retailer, with fakes for the site and the database."""

from datetime import UTC, datetime
from decimal import Decimal

from pharmavique.offers.application.crawl import CrawlBudget, InitialLoad
from pharmavique.offers.application.ports import (
    FetchFailed,
    FetchResult,
    SaveResult,
    SitemapEntry,
    SourceBlocked,
)
from pharmavique.offers.domain.model import Availability, JobType, ListingCategory, RunStatus
from pharmavique.offers.domain.page import ParsedProduct

NOW = datetime(2026, 11, 23, tzinfo=UTC)


def product(source_id: str, url: str) -> ParsedProduct:
    return ParsedProduct(
        source_id=source_id,
        url=url,
        name=f"Product {source_id}",
        language="en",
        brand=None,
        category_path=("Medicines", "Pain Relief"),
        description=None,
        ingredients_text=None,
        barcode=None,
        image_urls=(),
        price=Decimal("10"),
        currency="SAR",
        availability=Availability.IN_STOCK,
        pack_text=None,
        dosage_form_text=None,
    )


class FakeSitemap:
    def __init__(self, urls: list[str]) -> None:
        self.urls = urls

    async def entries(self) -> list[SitemapEntry]:
        return [SitemapEntry(u) for u in self.urls]


class FakeFetcher:
    def __init__(self, answers: dict[str, FetchResult | Exception]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    async def get(self, url: str) -> FetchResult:
        self.asked.append(url)
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeStore:
    def __init__(self, known: set[str] | None = None) -> None:
        self.known = known or set()
        self.saved: list[tuple[ParsedProduct, ListingCategory]] = []
        self.skipped: list[tuple[str, str]] = []
        self.runs: list[tuple[JobType, RunStatus | None, dict[str, int]]] = []

    async def ensure_retailer(self) -> None:
        return None

    async def known_urls(self) -> set[str]:
        return set(self.known)

    async def save(
        self, product: ParsedProduct, category: ListingCategory, now: datetime
    ) -> SaveResult:
        self.saved.append((product, category))
        return SaveResult(new=True, price_changed=False, details_changed=False, quarantined=False)

    async def skip(self, url: str, reason: str, now: datetime) -> None:
        self.skipped.append((url, reason))

    async def start_run(self, job: JobType, now: datetime) -> int:
        self.runs.append((job, None, {}))
        return len(self.runs)

    async def finish_run(
        self, run_id: int, status: RunStatus, counters: dict[str, int], now: datetime
    ) -> None:
        job, _, _ = self.runs[run_id - 1]
        self.runs[run_id - 1] = (job, status, counters)


def page(url: str) -> FetchResult:
    return FetchResult(200, f"page of {url}".encode())


def parse_all(html: str, url: str) -> ParsedProduct | None:
    if "skip-me" in url:
        return None
    return product(url.rsplit("/", 1)[-1], url)


def run(urls, answers, store, budget=None):
    use = InitialLoad(FakeSitemap(urls), FakeFetcher(answers), store, parse_all, lambda: NOW)
    return use.run(budget or CrawlBudget())


async def test_every_new_address_is_fetched_parsed_classified_and_saved() -> None:
    urls = ["https://s/a/1", "https://s/a/2"]
    store = FakeStore()
    task = run(urls, {u: page(u) for u in urls}, store)

    report = await task

    assert [p.source_id for p, _ in store.saved] == ["1", "2"]
    assert all(category is ListingCategory.MEDICINE for _, category in store.saved)
    assert report.status is RunStatus.COMPLETE
    assert report.counters["new"] == 2
    assert store.runs[0][1] is RunStatus.COMPLETE


async def test_addresses_already_stored_are_not_fetched_again_so_a_stopped_run_resumes() -> None:
    urls = ["https://s/a/1", "https://s/a/2", "https://s/a/3"]
    store = FakeStore(known={"https://s/a/1", "https://s/a/2"})
    fetcher_answers: dict[str, FetchResult | Exception] = {"https://s/a/3": page("https://s/a/3")}
    use = InitialLoad(
        FakeSitemap(urls), FakeFetcher(fetcher_answers), store, parse_all, lambda: NOW
    )

    report = await use.run(CrawlBudget())

    assert [p.source_id for p, _ in store.saved] == ["3"]
    assert report.status is RunStatus.COMPLETE


async def test_a_page_that_is_not_a_product_is_remembered_and_not_asked_again() -> None:
    urls = ["https://s/skip-me", "https://s/a/1"]
    store = FakeStore()
    task = run(urls, {u: page(u) for u in urls}, store)

    report = await task

    assert store.skipped == [("https://s/skip-me", "not_a_product")]
    assert report.counters["skipped"] == 1
    assert report.status is RunStatus.COMPLETE


async def test_a_gone_page_is_remembered() -> None:
    store = FakeStore()
    answers = {"https://s/a/1": FetchResult(404, b"")}
    task = run(["https://s/a/1"], answers, store)

    report = await task

    assert store.skipped == [("https://s/a/1", "gone")]
    assert report.status is RunStatus.COMPLETE


async def test_a_block_ends_the_run_at_once_and_is_never_retried() -> None:
    urls = ["https://s/a/1", "https://s/a/2", "https://s/a/3"]
    answers: dict[str, FetchResult | Exception] = {
        urls[0]: page(urls[0]),
        urls[1]: SourceBlocked("HTTP 429"),
        urls[2]: page(urls[2]),
    }
    store = FakeStore()
    fetcher = FakeFetcher(answers)
    use = InitialLoad(FakeSitemap(urls), fetcher, store, parse_all, lambda: NOW)

    report = await use.run(CrawlBudget())

    assert report.status is RunStatus.BLOCKED
    assert fetcher.asked == urls[:2]
    assert [p.source_id for p, _ in store.saved] == ["1"]


async def test_a_failed_page_is_counted_and_the_run_is_not_complete() -> None:
    urls = ["https://s/a/1", "https://s/a/2"]
    answers: dict[str, FetchResult | Exception] = {
        urls[0]: FetchFailed("boom"),
        urls[1]: page(urls[1]),
    }
    store = FakeStore()
    task = run(urls, answers, store)

    report = await task

    assert report.counters["failed"] == 1
    assert report.status is RunStatus.PARTIAL
    assert [p.source_id for p, _ in store.saved] == ["2"]


async def test_the_limit_stops_the_run_early_and_it_is_partial() -> None:
    urls = [f"https://s/a/{i}" for i in range(5)]
    store = FakeStore()
    task = run(urls, {u: page(u) for u in urls}, store, CrawlBudget(limit=2))

    report = await task

    assert len(store.saved) == 2
    assert report.status is RunStatus.PARTIAL
    assert report.counters["remaining"] == 3


async def test_nothing_in_the_sitemap_is_a_failed_run() -> None:
    task = run([], {}, FakeStore())

    assert (await task).status is RunStatus.FAILED
