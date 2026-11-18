"""The generic list crawler, on synthetic pages: nothing touches the network."""

from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import SourceBlocked
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_crawler import (
    ListCrawlConfig,
    ListCrawler,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.lists import (
    SFDA_LISTS,
    ListSpec,
    get_list,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore

BASE = "https://sfda.test"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
SPEC = ListSpec("shortage", "/en/shortage", "Shortage", 3)


def page_html(names: list[str], current: int, last: int) -> str:
    rows = "".join(f"<tr><td>{name}</td><td>Limited</td></tr>" for name in names)
    pager = (
        f'<li class="page-item active"><span class="page-link">{current + 1}</span></li>'
        f'<a href="?page=1">2</a><a href="?page={last}">last</a>'
    )
    return (
        "<table><thead><tr><th>Generic Name</th><th>Availability</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>{pager}"
    )


class FakeFetcher:
    def __init__(self, pages: list[list[str]]) -> None:
        self.calls: list[str] = []
        self.status = 200
        self.pages = pages

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        number = int(url.rsplit("=", 1)[1])
        shown = min(number, len(self.pages) - 1)  # past the end the site shows the last page again
        html = page_html(self.pages[shown], shown, len(self.pages) - 1)
        return FetchedPage(url, self.status, html, NOW)


class FixedClock:
    def now(self) -> datetime:
        return NOW


async def no_sleep(_: float) -> None:
    return None


def crawler(
    fetcher: FakeFetcher,
    tmp_path: Path,
    robots: str = "",
    config: ListCrawlConfig | None = None,
) -> tuple[ListCrawler, SnapshotStore]:
    store = SnapshotStore(tmp_path, "run-1")
    made = ListCrawler(
        spec=SPEC,
        fetcher=fetcher,
        store=store,
        robots=RobotsPolicy.from_text(robots, "test"),
        clock=FixedClock(),
        config=config or ListCrawlConfig(base_url=BASE, retry_wait=0.0),
        sleep=no_sleep,
    )
    return made, store


PAGES = [["amoxicillin", "insulin"], ["heparin", "morphine"], ["warfarin"]]


async def test_every_row_is_stored_with_provenance_and_the_pages_own_column_names(
    tmp_path: Path,
) -> None:
    c, store = crawler(FakeFetcher(PAGES), tmp_path)

    manifest = await c.run()

    records = store.read_records()
    assert manifest["status"] == "complete"
    assert [r["list"][0]["value"] for r in records] == [n for page in PAGES for n in page]
    first = records[0]
    assert first["list"][0]["label"] == "Generic Name"
    assert first["provenance"] == {
        "source": "sfda-list-shortage",
        "source_ref": f"{BASE}/en/shortage?page=0",
        "snapshot_id": "run-1",
        "fetched_at": NOW.isoformat(),
        "trust": "official",
    }
    assert manifest["list_completeness"]["gap"] == 0


async def test_a_rerun_reads_stored_pages_and_makes_no_requests(tmp_path: Path) -> None:
    fetcher = FakeFetcher(PAGES)
    c, store = crawler(fetcher, tmp_path)
    await c.run()
    made = len(fetcher.calls)
    before = store.read_records()

    again, _ = crawler(fetcher, tmp_path)
    await again.run()

    # only the page past the end is asked again: it is never stored, because a page that answers
    # an earlier page could just as well be a hole, and asking again later can differ
    assert len(fetcher.calls) == made + 1
    assert store.read_records() == before


async def test_robots_blocks_before_any_request(tmp_path: Path) -> None:
    fetcher = FakeFetcher(PAGES)
    c, store = crawler(fetcher, tmp_path, robots="User-agent: *\nDisallow: /en/shortage\n")

    with pytest.raises(SourceBlocked):
        await c.run()

    assert fetcher.calls == []
    assert (store.load_manifest() or {})["status"] == "blocked"


async def test_http_429_stops_the_crawl(tmp_path: Path) -> None:
    fetcher = FakeFetcher(PAGES)
    fetcher.status = 429
    c, store = crawler(fetcher, tmp_path)

    with pytest.raises(SourceBlocked):
        await c.run()

    assert len(fetcher.calls) == 1
    assert (store.load_manifest() or {})["status"] == "blocked"


async def test_a_page_limit_makes_a_partial_sample(tmp_path: Path) -> None:
    c, _ = crawler(FakeFetcher(PAGES), tmp_path, config=ListCrawlConfig(base_url=BASE, max_pages=1))

    manifest = await c.run()

    assert manifest["status"] == "partial"
    assert manifest["counts"]["records_written"] == 2


def test_list_catalog_has_unique_names_and_marks_the_three_giants() -> None:
    names = [spec.name for spec in SFDA_LISTS]
    assert len(names) == len(set(names))
    assert {s.name for s in SFDA_LISTS if s.is_giant} == {
        "medical-equipment",
        "food-products",
        "cosmetic-products",
    }
    assert get_list("pharmacies").path == "/en/list_registered_pharmacies"
    with pytest.raises(KeyError, match="unknown list"):
        get_list("nope")


def test_giant_lists_only_get_the_cheap_targeted_repair_passes() -> None:
    assert get_list("cosmetic-products").max_passes(8) == 3
    assert get_list("drug-shortage").max_passes(8) == 8


def test_sharded_store_keeps_folders_small(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path, "r", shard_size=1000)
    assert store.list_page_path(12).parent.name == "00000"
    assert store.list_page_path(2345).parent.name == "00002"
    assert SnapshotStore(tmp_path, "r").list_page_path(2345).parent.name == "list"


def linked_row(name: str, count: str) -> str:
    return (
        f'<tr><td>{name}</td><td>Limited</td><td><a href="/en/details_data?id={name}&amp;page=0">'
        f"Details</a>{count}</td></tr>"
    )


async def test_rows_that_share_a_link_id_but_differ_are_both_kept(tmp_path: Path) -> None:
    # The shortage list repeats a generic name once per group of trade names (seen 2026-11-17)
    rows = linked_row("CARBOPLATIN", "5") + linked_row("CARBOPLATIN", "1")
    rows += linked_row("CARBOPLATIN", "1")  # an identical repeat is still one row
    html = (
        "<table><thead><tr><th>Generic Name</th><th>Availability</th><th>Details</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        '<li class="page-item active"><span class="page-link">1</span></li><a href="?page=0">1</a>'
    )

    class OnePage(FakeFetcher):
        async def fetch(self, url: str) -> FetchedPage:
            self.calls.append(url)
            return FetchedPage(url, 200, html, NOW)

    c, store = crawler(OnePage([]), tmp_path, config=ListCrawlConfig(base_url=BASE, max_pages=1))
    await c.run()

    records = store.read_records()
    assert len(records) == 2
    assert {r["entity_key"] for r in records} == {"CARBOPLATIN"}
    assert len({r["key"] for r in records}) == 2


async def test_a_hole_page_is_recorded_not_stored_and_the_rest_of_the_list_is_kept(
    tmp_path: Path,
) -> None:
    class WithHole(FakeFetcher):
        async def fetch(self, url: str) -> FetchedPage:
            number = int(url.rsplit("=", 1)[1])
            if number == 1:  # the site's "No Results Found" page
                return FetchedPage(url, 200, "<html><body>No Results Found</body></html>", NOW)
            return await super().fetch(url)

    c, store = crawler(WithHole(PAGES), tmp_path)

    manifest = await c.run()

    assert [r["list"][0]["value"] for r in store.read_records()] == [
        "amoxicillin",
        "insulin",
        "warfarin",
    ]
    assert manifest["empty_pages"] == [1]
    assert manifest["status"] == "partial"
    assert not store.list_page_path(1).exists()  # not stored: asking again later may succeed


class TiedOrderFetcher:
    """A site whose default order has a tie (B is shown twice, C never) but sorts fine by title."""

    default_pages: ClassVar[list[list[str]]] = [["A", "B"], ["B", "D"]]
    sorted_pages: ClassVar[dict[str, list[list[str]]]] = {
        "asc": [["A", "B"], ["C", "D"]],
        "desc": [["D", "C"], ["B", "A"]],
    }

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        query = dict(part.split("=") for part in url.split("?", 1)[1].split("&"))
        pages = (
            self.sorted_pages[query["sort"]]
            if query.get("order") == "title"
            else self.default_pages
        )
        number = int(query["page"])
        shown = min(number, len(pages) - 1)
        return FetchedPage(url, 200, page_html(pages[shown], shown, len(pages) - 1), NOW)


async def test_a_gap_from_ties_in_the_default_order_is_closed_by_sorting_by_title(
    tmp_path: Path,
) -> None:
    spec = ListSpec("tied", "/en/tied", "Tied", 2, sortable=True)
    fetcher = TiedOrderFetcher()
    store = SnapshotStore(tmp_path, "run-1")
    made = ListCrawler(
        spec=spec,
        fetcher=fetcher,
        store=store,
        robots=RobotsPolicy.from_text("", "test"),
        clock=FixedClock(),
        config=ListCrawlConfig(base_url=BASE, retry_wait=0.0, list_patience=1),
        sleep=no_sleep,
    )
    manifest = await made.run()
    assert manifest["status"] == "complete"
    assert manifest["list_completeness"]["gap"] == 0
    assert manifest["counts"]["unique_rows"] == 4
    assert any("order=title&sort=asc" in call for call in fetcher.calls)


async def test_a_list_that_cannot_be_sorted_is_never_asked_for_a_sort(tmp_path: Path) -> None:
    fetcher = TiedOrderFetcher()
    store = SnapshotStore(tmp_path, "run-1")
    made = ListCrawler(
        spec=ListSpec("tied", "/en/tied", "Tied", 2),
        fetcher=fetcher,
        store=store,
        robots=RobotsPolicy.from_text("", "test"),
        clock=FixedClock(),
        config=ListCrawlConfig(base_url=BASE, retry_wait=0.0, list_patience=1),
        sleep=no_sleep,
    )
    manifest = await made.run()
    assert manifest["status"] == "partial"
    assert not any("order=" in call for call in fetcher.calls)
