"""Crawler tests use a fake fetcher and synthetic pages; nothing touches the network."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

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


def list_html(
    keys: list[str],
    last_page: int = 2,
    prices: dict[str, str] | None = None,
    current: int | None = None,
) -> str:
    prices = prices or {}
    rows = "".join(
        f"<tr><td>SCI-{k}</td><td>TRADE-{k}</td><td>5</td><td>Tablet</td>"
        f"<td>{prices.get(k, '9.5')}</td>"
        f'<td><a href="/en/details_data?nid=1&amp;id={k}&amp;page=0">Details</a></td></tr>'
        for k in keys
    )
    active = (
        f'<li class="page-item active"><span class="page-link">{current + 1}</span></li>'
        if current is not None
        else ""
    )
    pager = f'{active}<a href="?page=1">2</a><a href="?page={last_page}">last</a>'
    return f"<table><thead><tr>{HEADERS}</tr></thead><tbody>{rows}</tbody></table>{pager}"


def details_html(key: str, price: str = "9.5", status: str = "Valid") -> str:
    return (
        f"<table><tr><th>Register Number</th><td>{key}</td></tr>"
        f"<tr><th>Trade Name</th><td>TRADE-{key}</td></tr>"
        f"<tr><th>Authorization Status</th><td>{status}</td></tr>"
        f"<tr><th>Price</th><td>{price}</td></tr></table>"
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


def make_site(
    pages: list[list[str]],
    last_page: int | None = None,
    prices: dict[str, str] | None = None,
    statuses: dict[str, str] | None = None,
) -> FakeFetcher:
    prices = prices or {}
    statuses = statuses or {}
    fetcher = FakeFetcher()
    last = len(pages) - 1 if last_page is None else last_page
    for number, keys in enumerate(pages):
        fetcher.add(f"{BASE}/en/drugs-list?page={number}", list_html(keys, last, prices))
        for key in keys:
            for language in ("en", "ar"):
                url = f"{BASE}/{language}/details_data?nid=1&id={key}&page=0"
                html = details_html(key, prices.get(key, "9.5"), statuses.get(key, "Valid"))
                fetcher.add(url, html)
    fetcher.add(f"{BASE}/en/drugs-list?page={len(pages)}", list_html([], last))
    return fetcher


def crawler(
    fetcher: FakeFetcher,
    tmp_path: Path,
    config: CrawlConfig | None = None,
    robots: RobotsPolicy | None = None,
    run_id: str = "run-1",
) -> tuple[SfdaCrawler, SnapshotStore]:
    store = SnapshotStore(tmp_path, run_id)
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


# ---- update mode: after the first full crawl, only what changed is fetched -------------------


def detail_requests(fetcher: FakeFetcher, start: int) -> list[str]:
    return [url for url in fetcher.calls[start:] if "details_data" in url]


async def first_full_crawl(tmp_path: Path) -> dict[str, dict[str, Any]]:
    c, store = crawler(make_site(PAGES), tmp_path)
    await c.run()
    return {r["key"]: r for r in store.read_records()}


async def test_update_fetches_details_only_for_new_and_changed_drugs(tmp_path: Path) -> None:
    baseline = await first_full_crawl(tmp_path)
    site = make_site([["k1", "k2"], ["k3", "k4"], ["k5", "k6"]], prices={"k2": "12"})
    c, store = crawler(site, tmp_path, run_id="run-2")

    manifest = await c.update(baseline, recheck=0)

    fetched = detail_requests(site, 0)
    assert sorted(fetched) == sorted(
        f"{BASE}/{lang}/details_data?nid=1&id={key}&page=0"
        for key in ("k2", "k6")
        for lang in ("en", "ar")
    )
    assert manifest["refresh"] == {"new_or_changed": 2, "recheck": 0}
    assert manifest["status"] == "complete"
    records = {r["key"]: r for r in store.read_records()}
    assert sorted(records) == ["k1", "k2", "k3", "k4", "k5", "k6"]
    assert records["k2"]["list"]["price"] == "12"
    assert {f["label"]: f["value"] for f in records["k2"]["en"]}["Price"] == "12"


async def test_unchanged_drugs_are_carried_over_with_their_original_fetch_info(
    tmp_path: Path,
) -> None:
    baseline = await first_full_crawl(tmp_path)
    site = make_site(PAGES)
    c, store = crawler(site, tmp_path, run_id="run-2")

    manifest = await c.update(baseline, recheck=0)

    assert detail_requests(site, 0) == []
    k1 = {r["key"]: r for r in store.read_records()}["k1"]
    assert k1["en"] == baseline["k1"]["en"]
    assert k1["provenance"]["en_fetched_at"] == baseline["k1"]["provenance"]["en_fetched_at"]
    assert manifest["counts"]["details_carried_over"] == 10


async def test_a_drug_missing_from_the_new_list_is_not_in_the_new_records(tmp_path: Path) -> None:
    baseline = await first_full_crawl(tmp_path)
    c, store = crawler(make_site([["k1", "k2"], ["k4"], ["k5"]]), tmp_path, run_id="run-2")

    await c.update(baseline, recheck=0)

    assert [r["key"] for r in store.read_records()] == ["k1", "k2", "k4", "k5"]


async def test_details_only_changes_are_found_by_the_rotating_recheck(tmp_path: Path) -> None:
    baseline = await first_full_crawl(tmp_path)
    changed_site = make_site(PAGES, statuses={"k4": "Cancelled"})

    without, store0 = crawler(changed_site, tmp_path, run_id="run-2")
    await without.update(baseline, recheck=0)
    stale = {r["key"]: r for r in store0.read_records()}["k4"]
    assert {f["label"]: f["value"] for f in stale["en"]}["Authorization Status"] == "Valid"

    with_recheck, store1 = crawler(
        make_site(PAGES, statuses={"k4": "Cancelled"}), tmp_path, run_id="run-3"
    )
    await with_recheck.update(baseline, recheck=5)
    fresh = {r["key"]: r for r in store1.read_records()}["k4"]
    assert {f["label"]: f["value"] for f in fresh["en"]}["Authorization Status"] == "Cancelled"


async def test_recheck_takes_the_oldest_details_first(tmp_path: Path) -> None:
    baseline = await first_full_crawl(tmp_path)
    for index, key in enumerate(baseline):
        baseline[key]["provenance"]["en_fetched_at"] = f"2026-01-0{index + 1}T00:00:00+00:00"
    baseline["k3"]["provenance"]["en_fetched_at"] = "2020-01-01T00:00:00+00:00"
    site = make_site(PAGES)
    c, _ = crawler(site, tmp_path, run_id="run-2")

    await c.update(baseline, recheck=2)

    refreshed = {parse_qs(urlparse(url).query)["id"][0] for url in detail_requests(site, 0)}
    assert refreshed == {"k3", "k1"}


async def test_failed_details_for_a_changed_drug_fall_back_to_the_old_details(
    tmp_path: Path,
) -> None:
    baseline = await first_full_crawl(tmp_path)
    site = make_site(PAGES, prices={"k2": "12"})
    for language in ("en", "ar"):
        site.add(f"{BASE}/{language}/details_data?nid=1&id=k2&page=0", BLOCK_HTML)
    c, store = crawler(site, tmp_path, run_id="run-2")

    manifest = await c.update(baseline, recheck=0)

    k2 = {r["key"]: r for r in store.read_records()}["k2"]
    assert k2["list"]["price"] == "12"  # the new list price is kept
    assert k2["en"] == baseline["k2"]["en"]  # details stay the old ones
    assert "en:k2" in manifest["failures"]
    assert manifest["status"] == "partial"


async def test_update_needs_the_whole_list(tmp_path: Path) -> None:
    baseline = await first_full_crawl(tmp_path)
    c, _ = crawler(
        make_site(PAGES),
        tmp_path,
        CrawlConfig(base_url=BASE, max_pages=1, retry_wait=0.0),
        run_id="run-2",
    )

    with pytest.raises(CrawlError, match="whole list"):
        await c.update(baseline)


# ---- list quirks seen on the real site: it clamps to its last page, and sometimes answers
# ---- a page with the rows of the page before it (the pager label still looks right) ------------


def list_url(number: int) -> str:
    return f"{BASE}/en/drugs-list?page={number}"


def labelled_site(pages: list[list[str]], hint: int | None = None) -> FakeFetcher:
    """Every list page carries its pager label; requests past the end get the last page back."""
    last = len(pages) - 1
    shown_hint = last if hint is None else hint
    fetcher = make_site(pages, shown_hint)
    for number, keys in enumerate(pages):
        fetcher.add(list_url(number), list_html(keys, shown_hint, current=number))
    for number in range(len(pages), len(pages) + 5):
        fetcher.add(list_url(number), list_html(pages[-1], shown_hint, current=last))
    return fetcher


def glitch(fetcher: FakeFetcher, number: int, pages: list[list[str]], times: int | None) -> None:
    """Page `number` answers with the rows of the page before it (forever if times is None)."""
    wrong = FetchedPage(list_url(number), 200, list_html(pages[number - 1], 2, current=number), NOW)
    right = fetcher.responses[list_url(number)][0]
    answers: list[FetchedPage | Exception] = [wrong] * (times or 1)
    if times:
        answers.append(right)
    fetcher.add_sequence(list_url(number), answers)


def list_requests(fetcher: FakeFetcher) -> list[str]:
    return [u for u in fetcher.calls if "drugs-list" in u]


async def test_list_ends_where_the_pager_label_stops_matching_the_request(tmp_path: Path) -> None:
    site = labelled_site(PAGES)
    c, store = crawler(site, tmp_path)

    manifest = await c.run()

    assert [r["key"] for r in store.read_records()] == ["k1", "k2", "k3", "k4", "k5"]
    assert list_requests(site) == [list_url(n) for n in range(4)]  # page 3 is the clamped one
    assert manifest["counts"]["list_pages"] == 3
    assert manifest["list_completeness"] == {"expected": 5, "unique": 5, "gap": 0, "passes": 1}
    assert manifest["status"] == "complete"


async def test_a_page_that_repeats_the_one_before_is_fetched_again_and_repaired(
    tmp_path: Path,
) -> None:
    site = labelled_site(PAGES)
    glitch(site, 1, PAGES, times=1)  # first answer is wrong, the next one is right
    c, store = crawler(site, tmp_path)

    manifest = await c.run()

    assert [r["key"] for r in store.read_records()] == ["k1", "k2", "k3", "k4", "k5"]
    assert list_requests(site).count(list_url(1)) == 2
    assert manifest["list_completeness"] == {"expected": 5, "unique": 5, "gap": 0, "passes": 2}
    assert manifest["status"] == "complete"


async def test_a_gap_that_cannot_be_closed_is_reported_and_does_not_loop(tmp_path: Path) -> None:
    site = labelled_site(PAGES)
    glitch(site, 1, PAGES, times=None)  # page 1 never answers correctly
    c, store = crawler(site, tmp_path)

    manifest = await c.run()

    assert [r["key"] for r in store.read_records()] == ["k1", "k2", "k5"]
    assert manifest["list_completeness"]["gap"] == 2
    assert manifest["list_completeness"]["unique"] == 3
    assert manifest["status"] == "partial"
    assert list_requests(site).count(list_url(1)) <= 3  # the allowed passes, then it stops


async def test_a_list_that_seems_to_end_far_before_the_pager_says_is_refused(
    tmp_path: Path,
) -> None:
    site = labelled_site(PAGES, hint=40)
    c, _ = crawler(site, tmp_path)

    with pytest.raises(CrawlError, match="ends early"):
        await c.run()


async def test_a_list_that_never_ends_is_stopped_by_the_page_cap(tmp_path: Path) -> None:
    site = FakeFetcher()
    for number in range(30):
        site.add(list_url(number), list_html([f"x{number}"], 99))
    cfg = CrawlConfig(base_url=BASE, retry_wait=0.0, max_list_pages=10)
    c, _ = crawler(site, tmp_path, cfg)

    with pytest.raises(CrawlError, match="more than 10"):
        await c.run()
