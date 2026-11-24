"""The quick check of an official SFDA list: has anything changed since the last complete run?

A full crawl reads every page several times (the site's order is unstable), about an hour a day
for lists that gain one row a week (17 to 23 November 2026: one new row in eight lists). The quick
check reads two pages, the first and the last. The list is unchanged when the total the pages
give is the total of the last complete run and every row on both pages is already known: a new
row, an edited row (a row's key includes a hash of its cells) or a removed row changes one of
them. New rows appear on the first page (seen on 2026-11-23: the one new RMM row was on page 0).

What it cannot see is an edit in the middle of the list with the same total. So a full crawl still
runs when the last one is older than a week, and whenever the check is not sure.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pharmavique.ingestion.infrastructure.connectors.sfda_web.generic_list import (
    GenericPage,
    parse_generic_page,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.lists import ListSpec
from pharmavique.ingestion.infrastructure.connectors.sfda_web.polite_fetch import PoliteFetch
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore

FULL_CRAWL_EVERY_DAYS = 7


@dataclass(frozen=True, slots=True)
class QuickCheck:
    unchanged: bool
    total: int | None  # rows the two pages say the list holds, None when it cannot be told
    reason: str


@dataclass(frozen=True, slots=True)
class PreviousRun:
    run_id: str
    run_dir: Path
    full_crawl_at: datetime | None  # when this run's rows were last read in a full crawl


def unchanged(
    pages: dict[int, GenericPage], *, previous_keys: set[str], previous_count: int
) -> QuickCheck:
    """`pages` holds page 0 and, when the pager names a later last page, that page."""
    first = pages.get(0)
    if first is None or not first.rows:
        return QuickCheck(False, None, "the first page has no rows")
    last_no = first.last_page or 0
    last = pages.get(last_no)
    if last is None or not last.rows:
        return QuickCheck(False, None, "the last page has no rows")
    if last_no and last.current_page is not None and last.current_page != last_no:
        return QuickCheck(False, None, "the site answered the last page with another page")
    total = len(first.rows) * last_no + len(last.rows) if last_no else len(first.rows)
    if total != previous_count:
        return QuickCheck(False, total, f"the total changed: {total} now, {previous_count} before")
    if any(row.content_key not in previous_keys for row in first.rows):
        return QuickCheck(False, total, "a row on the first page is new or was edited")
    if any(row.content_key not in previous_keys for row in last.rows):
        return QuickCheck(False, total, "a row on the last page is new or was edited")
    return QuickCheck(True, total, "same total and the first and last pages are known")


def latest_complete_run(list_dir: Path, *, exclude: str) -> PreviousRun | None:
    """The newest earlier run of one list that finished complete and has its rows on disk."""
    if not list_dir.is_dir():
        return None
    for run_dir in sorted(list_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if run_dir.name == exclude or not run_dir.name.startswith("lists-"):
            continue
        manifest_path, records = run_dir / "manifest.json", run_dir / "records.jsonl"
        if not manifest_path.exists() or not records.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            continue
        stamp = manifest.get("full_crawl_at")
        return PreviousRun(run_dir.name, run_dir, datetime.fromisoformat(stamp) if stamp else None)
    return None


async def read_check_pages(
    spec: ListSpec, polite: PoliteFetch, base_url: str
) -> dict[int, GenericPage]:
    """Page 0 and the last page its pager names: two polite requests."""
    _, first = await polite.fetch_valid(spec.url(base_url, 0), parse_generic_page)
    pages = {0: first}
    if first.last_page:
        _, last = await polite.fetch_valid(spec.url(base_url, first.last_page), parse_generic_page)
        pages[first.last_page] = last
    return pages


async def reuse_if_unchanged(
    *,
    spec: ListSpec,
    store: SnapshotStore,
    polite: PoliteFetch,
    base_url: str,
    now: datetime,
    full_every: timedelta = timedelta(days=FULL_CRAWL_EVERY_DAYS),
) -> tuple[bool, str]:
    """When the list has not changed since the last complete run (and that run's rows were read
    in a full crawl less than `full_every` ago), write those rows as this run's and say so.
    Returns (reused, why)."""
    previous = latest_complete_run(store.run_dir.parent, exclude=store.run_id)
    if previous is None:
        return False, "no earlier complete run"
    if previous.full_crawl_at is None or now - previous.full_crawl_at >= full_every:
        return False, f"the last full crawl is older than {full_every.days} days"
    records = SnapshotStore(store.run_dir.parent, previous.run_id).read_records()
    check = unchanged(
        await read_check_pages(spec, polite, base_url),
        previous_keys={str(r["key"]) for r in records},
        previous_count=len(records),
    )
    if not check.unchanged:
        return False, check.reason
    store.write_records(records)
    store.save_manifest(
        {
            "run_id": store.run_id,
            "source": spec.source,
            "list": spec.name,
            "title": spec.title,
            "trust": "official",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "status": "complete",
            "mode": "quick_check_unchanged",
            "quick_check": check.reason,
            "reused_from": previous.run_id,
            "full_crawl_at": previous.full_crawl_at.isoformat(),
            "counts": {"records_written": len(records), "list_pages_fetched": 2},
        }
    )
    return True, check.reason
