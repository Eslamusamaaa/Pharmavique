"""The streaming list crawler for giant lists: rows go to disk page by page, never all in memory."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import (
    CrawlError,
    SourceBlocked,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_crawler import ListCrawlConfig
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_stream import (
    StreamingListCrawler,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.lists import ListSpec
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore

BASE = "https://sfda.test"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
SPEC = ListSpec("giant", "/en/giant", "A giant list", 3)


def page_html(names: list[str], current: int, last: int) -> str:
    rows = "".join(f"<tr><td>{n}</td><td>x</td></tr>" for n in names)
    pager = (
        f'<li class="page-item active"><span class="page-link">{current + 1}</span></li>'
        f'<a href="?page=1">2</a><a href="?page={last}">last</a>'
    )
    return (
        "<table><thead><tr><th>Brand</th><th>Note</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>{pager}"
    )


class FakeFetcher:
    def __init__(self, pages: list[list[str]], status: int = 200) -> None:
        self.pages = pages
        self.calls: list[int] = []
        self.status = status

    async def fetch(self, url: str) -> FetchedPage:
        number = int(url.rsplit("=", 1)[1])
        self.calls.append(number)
        shown = min(number, len(self.pages) - 1)  # past the end the site repeats the last page
        html = page_html(self.pages[shown], shown, len(self.pages) - 1)
        return FetchedPage(url, self.status, html, NOW)


class FixedClock:
    def now(self) -> datetime:
        return NOW


async def no_sleep(_: float) -> None:
    return None


def crawler(
    fetcher: FakeFetcher, tmp_path: Path, max_pages: int | None = None, robots: str = ""
) -> tuple[StreamingListCrawler, SnapshotStore]:
    store = SnapshotStore(tmp_path, "run-1", shard_size=2)
    made = StreamingListCrawler(
        spec=SPEC,
        fetcher=fetcher,
        store=store,
        robots=RobotsPolicy.from_text(robots, "test"),
        clock=FixedClock(),
        config=ListCrawlConfig(base_url=BASE, retry_wait=0.0, max_pages=max_pages),
        sleep=no_sleep,
    )
    return made, store


PAGES = [["a", "b"], ["c", "d"], ["e", "f"], ["g"]]


def names(store: SnapshotStore) -> list[str]:
    return [r["list"][0]["value"] for r in store.read_records()]


async def test_every_row_of_every_page_is_written_in_order_with_provenance(tmp_path: Path) -> None:
    c, store = crawler(FakeFetcher(PAGES), tmp_path)

    manifest = await c.run()

    assert names(store) == list("abcdefg")
    assert manifest["status"] == "complete"
    assert manifest["counts"]["unique_rows"] == 7
    first = store.read_records()[0]
    assert first["list_page"] == 0
    assert first["provenance"]["source"] == "sfda-list-giant"
    assert first["provenance"]["fetched_at"] == NOW.isoformat()
    assert first["provenance"]["source_ref"] == f"{BASE}/en/giant?page=0"


async def test_a_stopped_crawl_continues_after_its_last_page_without_asking_again(
    tmp_path: Path,
) -> None:
    first, store = crawler(FakeFetcher(PAGES), tmp_path, max_pages=2)
    await first.run()
    fetcher = FakeFetcher(PAGES)
    second, _ = crawler(fetcher, tmp_path)

    manifest = await second.run()

    assert names(store) == list("abcdefg")
    assert min(fetcher.calls) == 2  # pages 0 and 1 are not asked for again
    assert manifest["status"] == "complete"


async def test_a_row_seen_twice_is_written_once(tmp_path: Path) -> None:
    pages = [["a", "b"], ["b", "c"]]  # the site's unstable order repeats a row across pages
    c, store = crawler(FakeFetcher(pages), tmp_path)

    manifest = await c.run()

    assert names(store) == ["a", "b", "c"]
    assert manifest["counts"]["duplicate_rows"] == 1


async def test_a_sample_limited_by_pages_is_partial(tmp_path: Path) -> None:
    c, _ = crawler(FakeFetcher(PAGES), tmp_path, max_pages=1)

    manifest = await c.run()

    assert manifest["status"] == "partial"


async def test_robots_blocks_before_any_request(tmp_path: Path) -> None:
    fetcher = FakeFetcher(PAGES)
    c, store = crawler(fetcher, tmp_path, robots="User-agent: *\nDisallow: /en/giant\n")

    with pytest.raises(SourceBlocked):
        await c.run()

    assert fetcher.calls == []
    assert (store.load_manifest() or {})["status"] == "blocked"


async def test_a_list_that_never_ends_stops_at_the_page_cap(tmp_path: Path) -> None:
    class Endless(FakeFetcher):
        async def fetch(self, url: str) -> FetchedPage:
            number = int(url.rsplit("=", 1)[1])
            html = (
                "<table><thead><tr><th>Brand</th></tr></thead>"
                f"<tbody><tr><td>row{number}</td></tr></tbody></table>"
            )
            return FetchedPage(url, 200, html, NOW)

    c, _ = crawler(Endless([]), tmp_path)

    with pytest.raises(CrawlError, match="more than"):
        await c.run()


async def test_the_records_file_is_valid_json_lines_after_every_page(tmp_path: Path) -> None:
    fetcher = FakeFetcher(PAGES)
    c, store = crawler(fetcher, tmp_path, max_pages=3)
    await c.run()

    lines = store.records_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 6
    assert all(json.loads(line)["key"] for line in lines)


async def test_a_hole_page_is_skipped_recorded_and_not_stored(tmp_path: Path) -> None:
    class WithHole(FakeFetcher):
        async def fetch(self, url: str) -> FetchedPage:
            if url.endswith("page=1"):
                return FetchedPage(url, 200, "<html><body>No Results Found</body></html>", NOW)
            return await super().fetch(url)

    c, store = crawler(WithHole(PAGES), tmp_path)

    manifest = await c.run()

    assert names(store) == ["a", "b", "e", "f", "g"]
    assert manifest["empty_pages"] == [1]
    assert manifest["status"] == "partial"
    assert not store.list_page_path(1).exists()
