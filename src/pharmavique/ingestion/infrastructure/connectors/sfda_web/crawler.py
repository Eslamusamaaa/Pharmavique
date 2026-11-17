"""Crawl the public SFDA registered-drugs list politely and resumably.

Rules this crawler keeps, on purpose:
- it only reads public pages; it never touches the search/filter form (that form has a CAPTCHA,
  and a CAPTCHA is never bypassed);
- every URL is checked against robots.txt first;
- on HTTP 401/403/429 it stops at once instead of retrying;
- a page that does not parse is never stored, so a block page cannot become "data";
- progress is kept on disk, so a stopped run resumes where it stopped and re-runs are safe.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urljoin

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import FetchedPage, PageFetcher
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import (
    ListPage,
    ListRow,
    ParseError,
    parse_details_page,
    parse_list_page,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.shared_kernel.ports import Clock

SOURCE = "sfda-drugs-list-web"
LANGUAGES = ("en", "ar")
_T = TypeVar("_T")
_MAX_RECORDED_ITEMS = 200
_HINT_TOLERANCE = 5  # the pager's "last page" link has been seen off by a few pages
_TARGETED_PASSES = 3  # passes 2 and 3 refetch suspect pages only; later passes sweep every page


def _suspect_pages(pages: dict[int, tuple[ListRow, ...]]) -> set[int]:
    """Pages to fetch again: one that repeats the page before it, or shares drugs with another."""
    suspects: set[int] = set()
    first_seen: dict[str, int] = {}
    previous: tuple[str, ...] | None = None
    for number in sorted(pages):
        keys = tuple(row.registration_key for row in pages[number])
        if previous is not None and keys == previous:
            suspects.add(number)
        for key in keys:
            if key in first_seen and first_seen[key] != number:
                suspects.update({number, first_seen[key]})
            else:
                first_seen.setdefault(key, number)
        previous = keys
    return suspects


def list_fields(row: ListRow) -> dict[str, str]:
    """The list-page fields used to notice that a drug changed, without the page number."""
    return {
        "scientific_name": row.scientific_name,
        "trade_name": row.trade_name,
        "strength": row.strength,
        "dosage_form": row.dosage_form,
        "price": row.price,
    }


class CrawlError(Exception):
    """The crawl cannot continue."""


class SourceBlocked(CrawlError):
    """robots.txt forbids the URL or the site answered 401/403/429. Stop; do not work around it."""


class FetchFailed(CrawlError):
    """One URL could not be fetched or parsed after the allowed retries."""


class NotFound(FetchFailed):
    """The site answered 404 for this URL."""


class TooManyFailures(CrawlError):
    """Many pages in a row failed, which usually means the site is blocking or has changed."""


@dataclass(frozen=True, slots=True)
class CrawlConfig:
    base_url: str = "https://www.sfda.gov.sa"
    max_pages: int | None = None  # limit list pages (sampling)
    max_details: int | None = None  # limit drugs whose details are fetched (sampling)
    retries: int = 3
    retry_wait: float = 30.0
    max_consecutive_failures: int = 15
    max_list_pages: int = 5000  # hard stop if the list never seems to end
    max_list_passes: int = 8  # first pass plus repair passes (the list order is unstable)
    list_patience: int = 3  # stop after this many repair passes in a row that find nothing new
    user_agent: str = ""  # recorded in the manifest only; the fetcher sends it


class SfdaCrawler:
    def __init__(
        self,
        *,
        fetcher: PageFetcher,
        store: SnapshotStore,
        robots: RobotsPolicy,
        clock: Clock,
        config: CrawlConfig | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._fetcher = fetcher
        self._store = store
        self._robots = robots
        self._clock = clock
        self._config = config or CrawlConfig()
        self._sleep = sleep
        self._log = logging.getLogger("sfda.crawl")
        self._counts: dict[str, int] = {}

    # ---- public ------------------------------------------------------------------------------
    async def run(self) -> dict[str, Any]:
        """Full crawl: every list page, then the details of every drug (or of the first N)."""

        async def work(manifest: dict[str, Any]) -> None:
            rows = await self._crawl_list(manifest)
            keys = list(rows)[: self._config.max_details]
            await self._crawl_details(rows, manifest, keys)
            self._build_records(rows, keys, manifest, carry={})

        return await self._execute(work)

    async def update(
        self, baseline: Mapping[str, Mapping[str, Any]], recheck: int = 0
    ) -> dict[str, Any]:
        """Cheap refresh against `baseline` (the records of the last complete run).

        Reads every list page, fetches details only for new drugs, drugs whose list fields
        changed, and the `recheck` drugs whose details are oldest. Everything else is carried
        over from the baseline. Details-only changes are therefore found within
        ceil(total / recheck) runs.
        """
        if self._config.max_pages is not None:
            raise CrawlError("an update needs the whole list; do not set max_pages")

        async def work(manifest: dict[str, Any]) -> None:
            rows = await self._crawl_list(manifest)
            keys, new_or_changed = self._keys_to_refresh(rows, baseline, recheck)
            manifest["refresh"] = {
                "new_or_changed": new_or_changed,
                "recheck": len(keys) - new_or_changed,
            }
            await self._crawl_details(rows, manifest, keys)
            self._build_records(rows, list(rows), manifest, carry=baseline)

        return await self._execute(work)

    async def _execute(self, work: Callable[[dict[str, Any]], Awaitable[None]]) -> dict[str, Any]:
        manifest = self._store.load_manifest() or self._new_manifest()
        manifest.setdefault("resumed_at", [])
        if manifest.get("status") not in (None, "new"):
            manifest["resumed_at"].append(self._clock.now().isoformat())
        manifest["status"] = "running"
        manifest["config"] = asdict(self._config)
        self._store.save_manifest(manifest)

        try:
            await work(manifest)
        except SourceBlocked:
            manifest["status"] = "blocked"
            raise
        except CrawlError:
            manifest["status"] = "aborted"
            raise
        except BaseException:
            manifest["status"] = "interrupted"
            raise
        finally:
            manifest["counts"] = {**manifest.get("counts", {}), **self._counts}
            manifest["finished_at"] = self._clock.now().isoformat()
            self._store.save_manifest(manifest)
        return manifest

    # ---- phases ------------------------------------------------------------------------------
    async def _crawl_list(self, manifest: dict[str, Any]) -> dict[str, tuple[ListRow, int]]:
        """Read the whole list.

        Two quirks of the real site shape this:
        - past its last page the site does not answer "empty", it answers the last page again,
          but with the pager label of that last page. A label lower than the page we asked for
          therefore means "the list ended";
        - now and then a page comes back with the rows of the page before it (its pager label
          still looks right). Pages like that are fetched again in repair passes, and the manifest
          says how many drugs are still missing if some cannot be recovered.
        """
        pages: dict[int, tuple[ListRow, ...]] = {}
        hint: int | None = None
        real_last: int | None = None
        page_no = 0

        while self._config.max_pages is None or page_no < self._config.max_pages:
            if page_no >= self._config.max_list_pages:
                raise CrawlError(f"the list has more than {self._config.max_list_pages} pages")
            parsed = await self._get_list_page(page_no, 1)
            if page_no == 0:
                hint = parsed.last_page
            clamped = parsed.current_page is not None and parsed.current_page < page_no
            if clamped or not parsed.rows:
                if hint is not None and page_no < hint - _HINT_TOLERANCE:
                    raise CrawlError(
                        f"the list ends early at page {page_no} but the pager says {hint}"
                    )
                if not clamped and hint is not None and page_no <= hint:
                    raise CrawlError(f"list page {page_no} is empty but the pager says {hint}")
                real_last = page_no - 1
                break
            pages[page_no] = parsed.rows
            if page_no % 20 == 0:
                self._log.info("list page %s of %s", page_no, hint)
            page_no += 1

        known: dict[str, tuple[ListRow, int]] = {}
        duplicates: list[str] = []
        for number in sorted(pages):
            for row in pages[number]:
                if row.registration_key in known:
                    duplicates.append(row.registration_key)
                else:
                    known[row.registration_key] = (row, number)

        passes = 1
        if self._config.max_pages is None and real_last is not None:
            passes = await self._repair_list(pages, known, real_last)
            expected = self._expected_total(pages, real_last)
            manifest["list_completeness"] = {
                "expected": expected,
                "unique": len(known),
                "gap": max(expected - len(known), 0),
                "passes": passes,
            }
            if len(known) < expected:
                self._log.warning(
                    "the list shows %s drugs but %s were expected; see manifest",
                    len(known),
                    expected,
                )

        rows = dict(sorted(known.items(), key=lambda item: item[1][1]))
        total_rows = sum(len(page) for page in pages.values())
        manifest["last_page_in_pager"] = hint
        manifest["duplicates"] = duplicates[:_MAX_RECORDED_ITEMS]
        self._counts["list_pages"] = (real_last + 1) if real_last is not None else page_no
        self._counts["unique_drugs"] = len(rows)
        self._counts["duplicate_rows"] = max(total_rows - len(rows), 0)
        return rows

    async def _get_list_page(self, page_no: int, pass_no: int) -> ListPage:
        return await self._load_or_fetch(
            self._store.list_page_path(page_no, pass_no),
            self._list_url(page_no),
            parse_list_page,
            "list",
        )

    async def _repair_list(
        self,
        pages: dict[int, tuple[ListRow, ...]],
        known: dict[str, tuple[ListRow, int]],
        real_last: int,
    ) -> int:
        """Fetch pages again and keep the union of everything seen. Returns the passes used.

        The site's list order is unstable: every fetch of a page can show different rows near
        its edges, so one drug can appear on two pages while another appears on none. Fetching
        again converges on the full list. Passes 2 and 3 target pages that look wrong; later
        passes sweep every page, because a skipped drug leaves no duplicate to point at. It stops
        when nothing is missing, after `list_patience` passes in a row that found nothing new, or
        at `max_list_passes`.
        """
        passes = 1
        idle = 0
        while passes < self._config.max_list_passes:
            if len(known) >= self._expected_total(pages, real_last):
                break
            suspects = _suspect_pages(pages)
            targets = suspects if passes < _TARGETED_PASSES and suspects else set(pages)
            passes += 1
            self._log.info(
                "repair pass %s: fetching %s list pages again (%s of %s drugs known)",
                passes,
                len(targets),
                len(known),
                self._expected_total(pages, real_last),
            )
            gained = 0
            for number in sorted(targets):
                parsed = await self._get_list_page(number, passes)
                if parsed.current_page is not None and parsed.current_page != number:
                    continue  # the site answered with a different page; ignore it
                pages[number] = parsed.rows
                for row in parsed.rows:
                    if row.registration_key not in known:
                        known[row.registration_key] = (row, number)
                        gained += 1
            idle = idle + 1 if gained == 0 else 0
            if idle >= self._config.list_patience:
                break
        return passes

    @staticmethod
    def _expected_total(pages: dict[int, tuple[ListRow, ...]], real_last: int) -> int:
        """Drugs the list should hold: full pages (sized like page 0) plus the last page."""
        return len(pages[0]) * real_last + len(pages[real_last])

    def _keys_to_refresh(
        self,
        rows: dict[str, tuple[ListRow, int]],
        baseline: Mapping[str, Mapping[str, Any]],
        recheck: int,
    ) -> tuple[list[str], int]:
        def unchanged(key: str) -> bool:
            old = baseline.get(key)
            if old is None:
                return False
            old_list = {k: v for k, v in old["list"].items() if k != "list_page"}
            return old_list == list_fields(rows[key][0])

        changed = [key for key in rows if not unchanged(key)]
        changed_set = set(changed)
        stale = [key for key in rows if key not in changed_set]
        # oldest details first; a drug with no stored fetch time (or no details) sorts first
        stale.sort(key=lambda k: str(baseline[k].get("provenance", {}).get("en_fetched_at", "")))
        return changed + stale[: max(recheck, 0)], len(changed)

    async def _crawl_details(
        self,
        rows: dict[str, tuple[ListRow, int]],
        manifest: dict[str, Any],
        keys: list[str],
    ) -> None:
        failures: dict[str, str] = manifest.get("failures", {})
        consecutive = 0

        for index, key in enumerate(keys):
            row = rows[key][0]
            for language in LANGUAGES:
                path = self._store.details_path(language, key)
                if self._store.has(path):
                    failures.pop(f"{language}:{key}", None)
                    self._bump("details_reused")
                    continue
                url = self._details_url(row, language)
                try:
                    page, _ = await self._fetch_valid(url, parse_details_page)
                except SourceBlocked:
                    raise
                except FetchFailed as exc:
                    self._bump("details_failed")
                    if len(failures) < _MAX_RECORDED_ITEMS:
                        failures[f"{language}:{key}"] = str(exc)
                    consecutive += 1
                    if consecutive >= self._config.max_consecutive_failures:
                        raise TooManyFailures(
                            f"{consecutive} details pages failed in a row"
                        ) from exc
                    continue
                self._store.save_page(path, page)
                consecutive = 0
                self._bump("details_fetched")
            if index % 50 == 0:
                self._log.info("details %s of %s drugs", index, len(keys))
                manifest["failures"] = failures
                manifest["counts"] = {**manifest.get("counts", {}), **self._counts}
                self._store.save_manifest(manifest)
        manifest["failures"] = failures

    def _build_records(
        self,
        rows: dict[str, tuple[ListRow, int]],
        keys: list[str],
        manifest: dict[str, Any],
        carry: Mapping[str, Mapping[str, Any]],
    ) -> None:
        records: list[dict[str, Any]] = []
        mismatched: list[str] = []
        complete = True

        for key in keys:
            row, page_no = rows[key]
            record: dict[str, Any] = {
                "key": key,
                "list": {**list_fields(row), "list_page": page_no},
                "provenance": {
                    "source": SOURCE,
                    "snapshot_id": self._store.run_id,
                    "trust": "official",
                },
            }
            for language in LANGUAGES:
                path = self._store.details_path(language, key)
                if not self._store.has(path):
                    old = carry.get(key)
                    if old is not None and old.get(language):
                        # no fresh page in this run: keep the baseline's details and say so
                        record[language] = old[language]
                        for suffix in ("source_ref", "fetched_at", "snapshot_id"):
                            name = f"{language}_{suffix}"
                            if name in old.get("provenance", {}):
                                record["provenance"][name] = old["provenance"][name]
                        self._bump("details_carried_over")
                    else:
                        record[language] = None
                        complete = False
                    continue
                stored = self._store.load_page(path)
                fields = parse_details_page(stored.html).fields
                record[language] = [{"label": f.label, "value": f.value} for f in fields]
                record["provenance"][f"{language}_source_ref"] = stored.url
                record["provenance"][f"{language}_fetched_at"] = stored.fetched_at.isoformat()
                record["provenance"][f"{language}_snapshot_id"] = self._store.run_id
                if language == "en" and not any(f.value == key for f in fields):
                    mismatched.append(key)
            records.append(record)

        self._counts["records_written"] = self._store.write_records(records)
        manifest["key_not_found_in_details"] = mismatched[:_MAX_RECORDED_ITEMS]
        partial = (
            not complete
            or bool(manifest.get("failures"))
            or manifest.get("list_completeness", {}).get("gap", 0) > 0
            or self._config.max_pages is not None
            or self._config.max_details is not None
        )
        manifest["status"] = "partial" if partial else "complete"

    # ---- fetching ----------------------------------------------------------------------------
    async def _load_or_fetch(
        self, path: Path, url: str, parse: Callable[[str], _T], kind: str
    ) -> _T:
        if self._store.has(path):
            try:
                parsed = parse(self._store.load_page(path).html)
            except ParseError:
                self._log.warning("stored %s page is unreadable, fetching again: %s", kind, path)
            else:
                self._bump(f"{kind}_pages_reused")
                return parsed
        page, parsed = await self._fetch_valid(url, parse)
        self._store.save_page(path, page)
        self._bump(f"{kind}_pages_fetched")
        return parsed

    async def _fetch_valid(self, url: str, parse: Callable[[str], _T]) -> tuple[FetchedPage, _T]:
        if not self._robots.allows(url):
            raise SourceBlocked(f"robots.txt does not allow {url}")

        last_error: Exception | None = None
        for attempt in range(1, self._config.retries + 1):
            try:
                page = await self._fetcher.fetch(url)
            except Exception as exc:  # network errors and timeouts are retried
                last_error = exc
            else:
                if page.status in (401, 403, 429):
                    raise SourceBlocked(f"HTTP {page.status} for {url}")
                if page.status == 404:
                    raise NotFound(f"HTTP 404 for {url}")
                if page.status == 200:
                    try:
                        return page, parse(page.html)
                    except ParseError as exc:
                        last_error = exc
                else:
                    last_error = FetchFailed(f"HTTP {page.status}")
            if attempt < self._config.retries:
                await self._sleep(self._config.retry_wait * attempt)
        raise FetchFailed(f"{url}: {last_error}")

    # ---- helpers -----------------------------------------------------------------------------
    def _list_url(self, page_no: int) -> str:
        return f"{self._config.base_url}/en/drugs-list?page={page_no}"

    def _details_url(self, row: ListRow, language: str) -> str:
        href = row.details_href
        if not href.startswith("/en/"):
            raise CrawlError(f"unexpected details link: {href!r}")
        return urljoin(self._config.base_url + "/", f"/{language}/" + href[len("/en/") :])

    def _bump(self, name: str) -> None:
        self._counts[name] = self._counts.get(name, 0) + 1

    def _new_manifest(self) -> dict[str, Any]:
        return {
            "run_id": self._store.run_id,
            "source": SOURCE,
            "base_url": self._config.base_url,
            "user_agent": self._config.user_agent,
            "trust": "official",
            "license_status": "unverified, see docs/DATA_SOURCES.md",
            "started_at": self._clock.now().isoformat(),
            "status": "new",
        }
