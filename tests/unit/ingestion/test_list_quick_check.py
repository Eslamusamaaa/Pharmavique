"""The quick check of an SFDA list: two pages decide whether the full crawl can be skipped."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pharmavique.ingestion.infrastructure.connectors.sfda_web.generic_list import (
    GenericPage,
    GenericRow,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_quick_check import (
    QuickCheck,
    latest_complete_run,
    unchanged,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore


def row(name: str) -> GenericRow:
    return GenericRow(cells=(("Title", name),), link=None)


def page(names: list[str], last: int | None, current: int | None) -> GenericPage:
    return GenericPage(("Title",), tuple(row(n) for n in names), last, current)


def pages(first: list[str], last_rows: list[str], last: int = 2) -> dict[int, GenericPage]:
    return {0: page(first, last, 0), last: page(last_rows, last, last)}


KNOWN = {row(n).content_key for n in ["a", "b", "c", "x", "y"]}
# 2 full pages of 2 rows before the last page, which has 1: 2 * 2 + 1 = 5 rows


def test_the_same_total_and_known_rows_on_both_pages_is_unchanged() -> None:
    check = unchanged(pages(["a", "b"], ["y"]), previous_keys=KNOWN, previous_count=5)

    assert check == QuickCheck(True, 5, "same total and the first and last pages are known")


@pytest.mark.parametrize(
    ("first", "last_rows", "reason"),
    [
        (["new", "a"], ["y"], "a row on the first page is new or was edited"),
        (["a", "b"], ["y", "z"], "the total changed: 6 now, 5 before"),
        (["a", "b"], ["new"], "a row on the last page is new or was edited"),
    ],
)
def test_a_new_row_an_edit_or_another_total_needs_the_full_crawl(
    first: list[str], last_rows: list[str], reason: str
) -> None:
    check = unchanged(pages(first, last_rows), previous_keys=KNOWN, previous_count=5)

    assert check.unchanged is False
    assert check.reason == reason


def test_a_page_that_answers_another_page_number_needs_the_full_crawl() -> None:
    odd = {0: page(["a", "b"], 2, 0), 2: page(["y"], 2, 1)}  # the site clamped the last page

    assert unchanged(odd, previous_keys=KNOWN, previous_count=5).unchanged is False


def test_a_one_page_list_is_checked_on_that_page() -> None:
    single = {0: page(["a", "b"], None, 0)}

    assert unchanged(single, previous_keys=KNOWN, previous_count=2).unchanged is True


def test_the_latest_complete_run_with_records_and_a_recent_full_crawl_is_used(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 24, tzinfo=UTC)

    def run(run_id: str, status: str, full: datetime | None, records: bool = True) -> None:
        store = SnapshotStore(tmp_path, run_id)
        manifest = {"run_id": run_id, "status": status}
        if full is not None:
            manifest["full_crawl_at"] = full.isoformat()
        store.save_manifest(manifest)
        if records:
            store.write_records([{"key": "a"}])

    run("lists-20261121", "complete", now - timedelta(days=3))
    run("lists-20261122", "partial", now - timedelta(days=2))
    run("lists-20261123", "complete", now - timedelta(days=1), records=False)
    run("lists-1", "complete", None)

    found = latest_complete_run(tmp_path, exclude="lists-20261124")

    assert found is not None
    assert found.run_id == "lists-20261121"
    assert found.full_crawl_at == now - timedelta(days=3)


class FakePolite:
    """Answers list pages from a dict, as `PoliteFetch.fetch_valid` would after parsing."""

    def __init__(self, by_page: dict[int, GenericPage]) -> None:
        self.by_page = by_page
        self.asked: list[str] = []

    async def fetch_valid(self, url: str, parse: object) -> tuple[None, GenericPage]:
        self.asked.append(url)
        return None, self.by_page[int(url.split("page=")[1].split("&")[0])]


def previous_run(root: Path, full: datetime, names: list[str]) -> None:
    store = SnapshotStore(root, "lists-20261123")
    store.save_manifest(
        {"run_id": "lists-20261123", "status": "complete", "full_crawl_at": full.isoformat()}
    )
    store.write_records([{"key": row(n).content_key, "name": n} for n in names])


async def test_an_unchanged_list_reuses_the_last_run_after_two_requests(tmp_path: Path) -> None:
    from typing import Any, cast

    from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_quick_check import (
        reuse_if_unchanged,
    )
    from pharmavique.ingestion.infrastructure.connectors.sfda_web.lists import get_list

    now = datetime(2026, 11, 24, tzinfo=UTC)
    previous_run(tmp_path, now - timedelta(days=1), ["a", "b", "c", "x", "y"])
    polite = FakePolite(pages(["a", "b"], ["y"]))
    store = SnapshotStore(tmp_path, "lists-20261124")

    reused, _ = await reuse_if_unchanged(
        spec=get_list("rmm"), store=store, polite=cast(Any, polite), base_url="https://s", now=now
    )

    assert reused is True
    assert len(polite.asked) == 2
    assert [r["name"] for r in store.read_records()] == ["a", "b", "c", "x", "y"]
    manifest = store.load_manifest()
    assert manifest is not None
    assert manifest["status"] == "complete"
    assert manifest["reused_from"] == "lists-20261123"


async def test_a_full_crawl_older_than_a_week_is_never_skipped(tmp_path: Path) -> None:
    from typing import Any, cast

    from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_quick_check import (
        reuse_if_unchanged,
    )
    from pharmavique.ingestion.infrastructure.connectors.sfda_web.lists import get_list

    now = datetime(2026, 11, 24, tzinfo=UTC)
    previous_run(tmp_path, now - timedelta(days=8), ["a", "b", "c", "x", "y"])
    polite = FakePolite(pages(["a", "b"], ["y"]))

    reused, why = await reuse_if_unchanged(
        spec=get_list("rmm"),
        store=SnapshotStore(tmp_path, "lists-20261124"),
        polite=cast(Any, polite),
        base_url="https://s",
        now=now,
    )

    assert reused is False
    assert polite.asked == []
    assert "older than 7 days" in why
