"""The generic list crawler, on synthetic pages: nothing touches the network."""

from datetime import UTC, datetime
from pathlib import Path

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

    assert len(fetcher.calls) == made
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
