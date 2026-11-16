"""Crawler tests use a fake fetcher and synthetic pages; nothing touches the network."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.connectors.sfda_web.crawler import (
    CrawlConfig,
    CrawlError,
    SfdaCrawler,
    SourceBlocked,
    TooManyFailures,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore

BASE = "https://sfda.test"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
BLOCK_HTML = "<html><body>Please verify you are human</body></html>"
HEADERS = (
    "<th>Scientific Name</th><th>Trade Name</th><th>Strength</th>"
    "<th>Dosage Form</th><th>Price</th><th>Details</th>"
)


def list_html(keys: list[str], last_page: int = 2) -> str:
    rows = "".join(
        f"<tr><td>SCI-{k}</td><td>TRADE-{k}</td><td>5</td><td>Tablet</td><td>9.5</td>"
        f'<td><a href="/en/details_data?nid=1&amp;id={k}&amp;page=0">Details</a></td></tr>'
        for k in keys
    )
    pager = f'<a href="?page=1">2</a><a href="?page={last_page}">last</a>'
    return f"<table><thead><tr>{HEADERS}</tr></thead><tbody>{rows}</tbody></table>{pager}"


def details_html(key: str) -> str:
    return (
        f"<table><tr><th>Register Number</th><td>{key}</td></tr>"
        f"<tr><th>Trade Name</th><td>TRADE-{key}</td></tr>"
        "<tr><th>Price</th><td>9.5</td></tr></table>"
    )


class FakeFetcher:
    def __init__(self) -> None:
        self.responses: dict[str, list[FetchedPage | Exception]] = {}
        self.calls: list[str] = []

    def add(self, url: str, html: str, status: int = 200) -> None:
        self.responses[url] = [FetchedPage(url, status, html, NOW)]

    def add_sequence(self, url: str, items: list[FetchedPage | Exception]) -> None:
        self.responses[url] = items

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        queue = self.responses.get(url)
        if not queue:
            return FetchedPage(url, 404, "", NOW)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


class FixedClock:
    def now(self) -> datetime:
        return NOW


async def no_sleep(_: float) -> None:
    return None


def make_site(pages: list[list[str]], last_page: int | None = None) -> FakeFetcher:
    fetcher = FakeFetcher()
    last = len(pages) - 1 if last_page is None else last_page
    for number, keys in enumerate(pages):
        fetcher.add(f"{BASE}/en/drugs-list?page={number}", list_html(keys, last))
        for key in keys:
            for language in ("en", "ar"):
                url = f"{BASE}/{language}/details_data?nid=1&id={key}&page=0"
                fetcher.add(url, details_html(key))
    fetcher.add(f"{BASE}/en/drugs-list?page={len(pages)}", list_html([], last))
    return fetcher


def crawler(
    fetcher: FakeFetcher,
    tmp_path: Path,
    config: CrawlConfig | None = None,
    robots: RobotsPolicy | None = None,
) -> tuple[SfdaCrawler, SnapshotStore]:
    store = SnapshotStore(tmp_path, "run-1")
    cfg = config or CrawlConfig(base_url=BASE, retry_wait=0.0)
    policy = robots or RobotsPolicy.from_text("", "test")
    return (
        SfdaCrawler(
            fetcher=fetcher,
            store=store,
            robots=policy,
            clock=FixedClock(),
            config=cfg,
            sleep=no_sleep,
        ),
        store,
    )


PAGES = [["k1", "k2"], ["k3", "k4"], ["k5"]]


async def test_full_crawl_writes_records_with_both_languages(tmp_path: Path) -> None:
    c, store = crawler(make_site(PAGES), tmp_path)

    manifest = await c.run()

    records = store.read_records()
    assert [r["key"] for r in records] == ["k1", "k2", "k3", "k4", "k5"]
    first = records[0]
    assert first["list"]["trade_name"] == "TRADE-k1"
    assert {f["label"]: f["value"] for f in first["en"]}["Register Number"] == "k1"
    assert first["ar"] is not None
    assert first["provenance"]["source"] == "sfda-drugs-list-web"
    assert first["provenance"]["trust"] == "official"
    assert first["provenance"]["en_source_ref"] == f"{BASE}/en/details_data?nid=1&id=k1&page=0"
    assert manifest["status"] == "complete"
    assert manifest["counts"]["unique_drugs"] == 5
    assert manifest["counts"]["details_fetched"] == 10


async def test_rerun_makes_no_requests_and_keeps_the_same_records(tmp_path: Path) -> None:
    fetcher = make_site(PAGES)
    c, store = crawler(fetcher, tmp_path)
    await c.run()
    before = store.read_records()
    calls_after_first_run = len(fetcher.calls)

    c2, _ = crawler(fetcher, tmp_path)
    await c2.run()

    # every list page (including the empty one that ends the list) and every details page is reused
    assert len(fetcher.calls) == calls_after_first_run
    assert store.read_records() == before


async def test_resume_fetches_only_what_is_missing(tmp_path: Path) -> None:
    fetcher = make_site(PAGES)
    partial, _ = crawler(
        fetcher, tmp_path, CrawlConfig(base_url=BASE, max_details=2, retry_wait=0.0)
    )
    first = await partial.run()
    assert first["status"] == "partial"
    calls_before = len(fetcher.calls)

    full, store = crawler(fetcher, tmp_path)
    manifest = await full.run()

    new_calls = fetcher.calls[calls_before:]
    assert sum("details_data" in url for url in new_calls) == 6  # 3 remaining drugs x 2 languages
    assert manifest["status"] == "complete"
    assert len(store.read_records()) == 5


async def test_http_403_stops_the_crawl_and_keeps_earlier_work(tmp_path: Path) -> None:
    fetcher = make_site(PAGES)
    fetcher.add(f"{BASE}/en/details_data?nid=1&id=k3&page=0", "denied", status=403)
    c, store = crawler(fetcher, tmp_path)

    with pytest.raises(SourceBlocked):
        await c.run()

    assert store.load_manifest()["status"] == "blocked"  # type: ignore[index]
    assert store.has(store.details_path("en", "k1"))
    assert store.has(store.details_path("ar", "k2"))
    assert not store.has(store.details_path("en", "k3"))


async def test_robots_rule_blocks_before_any_details_request(tmp_path: Path) -> None:
    fetcher = make_site(PAGES)
    robots = RobotsPolicy.from_text("User-agent: *\nDisallow: /en/details_data\n", "test")
    c, _ = crawler(fetcher, tmp_path, robots=robots)

    with pytest.raises(SourceBlocked):
        await c.run()

    assert not any("details_data" in url for url in fetcher.calls)


async def test_unparseable_page_is_retried_never_stored_and_recorded(tmp_path: Path) -> None:
    fetcher = make_site(PAGES)
    bad_url = f"{BASE}/en/details_data?nid=1&id=k1&page=0"
    fetcher.add(bad_url, BLOCK_HTML)
    c, store = crawler(fetcher, tmp_path)

    manifest = await c.run()

    assert fetcher.calls.count(bad_url) == 3  # initial try plus two retries
    assert not store.has(store.details_path("en", "k1"))
    assert "en:k1" in manifest["failures"]
    assert manifest["status"] == "partial"
    first = store.read_records()[0]
    assert first["key"] == "k1"
    assert first["en"] is None
    assert first["ar"] is not None


async def test_network_errors_are_retried(tmp_path: Path) -> None:
    fetcher = make_site(PAGES)
    url = f"{BASE}/en/drugs-list?page=0"
    page = FetchedPage(url, 200, list_html(["k1", "k2"], 2), NOW)
    fetcher.add_sequence(url, [TimeoutError("slow"), page])
    c, _ = crawler(fetcher, tmp_path)

    manifest = await c.run()

    assert manifest["status"] == "complete"
    assert fetcher.calls.count(url) == 2


async def test_many_failures_in_a_row_abort_the_run(tmp_path: Path) -> None:
    fetcher = make_site(PAGES)
    for key in ("k1", "k2", "k3"):
        for language in ("en", "ar"):
            fetcher.add(f"{BASE}/{language}/details_data?nid=1&id={key}&page=0", BLOCK_HTML)
    cfg = CrawlConfig(base_url=BASE, retry_wait=0.0, max_consecutive_failures=2)
    c, store = crawler(fetcher, tmp_path, cfg)

    with pytest.raises(TooManyFailures):
        await c.run()

    assert store.load_manifest()["status"] == "aborted"  # type: ignore[index]


async def test_duplicate_rows_keep_the_first_and_are_reported(tmp_path: Path) -> None:
    c, store = crawler(make_site([["k1", "k2"], ["k2", "k3"]]), tmp_path)

    manifest = await c.run()

    assert [r["key"] for r in store.read_records()] == ["k1", "k2", "k3"]
    assert manifest["duplicates"] == ["k2"]


async def test_empty_page_before_the_pager_end_is_an_error(tmp_path: Path) -> None:
    fetcher = make_site([["k1"], [], ["k3"]], last_page=2)
    c, _ = crawler(fetcher, tmp_path)

    with pytest.raises(CrawlError, match="empty"):
        await c.run()


async def test_page_limit_makes_a_partial_sample(tmp_path: Path) -> None:
    c, store = crawler(
        make_site(PAGES), tmp_path, CrawlConfig(base_url=BASE, max_pages=1, retry_wait=0.0)
    )

    manifest = await c.run()

    assert [r["key"] for r in store.read_records()] == ["k1", "k2"]
    assert manifest["status"] == "partial"
