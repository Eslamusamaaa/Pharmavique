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
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urljoin

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import FetchedPage, PageFetcher
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import (
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
    retry_wait: float = 10.0
    max_consecutive_failures: int = 15
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
        manifest = self._store.load_manifest() or self._new_manifest()
        manifest.setdefault("resumed_at", [])
        if manifest.get("status") not in (None, "new"):
            manifest["resumed_at"].append(self._clock.now().isoformat())
        manifest["status"] = "running"
        manifest["config"] = asdict(self._config)
        self._store.save_manifest(manifest)

        try:
            rows = await self._crawl_list(manifest)
            await self._crawl_details(rows, manifest)
            self._build_records(rows, manifest)
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
        rows: dict[str, tuple[ListRow, int]] = {}
        duplicates: list[str] = []
        last_page: int | None = None
        page_no = 0

        while self._config.max_pages is None or page_no < self._config.max_pages:
            parsed = await self._load_or_fetch(
                self._store.list_page_path(page_no),
                self._list_url(page_no),
                parse_list_page,
                "list",
            )
            if page_no == 0:
                last_page = parsed.last_page
            if not parsed.rows:
                if last_page is not None and page_no <= last_page:
                    raise CrawlError(f"list page {page_no} is empty but the pager says {last_page}")
                break
            for row in parsed.rows:
                if row.registration_key in rows:
                    duplicates.append(row.registration_key)
                else:
                    rows[row.registration_key] = (row, page_no)
            if page_no % 20 == 0:
                self._log.info("list page %s of %s, %s drugs so far", page_no, last_page, len(rows))
            page_no += 1

        manifest["last_page_in_pager"] = last_page
        manifest["duplicates"] = duplicates[:_MAX_RECORDED_ITEMS]
        self._counts["list_pages"] = page_no
        self._counts["unique_drugs"] = len(rows)
        self._counts["duplicate_rows"] = len(duplicates)
        return rows

    async def _crawl_details(
        self, rows: dict[str, tuple[ListRow, int]], manifest: dict[str, Any]
    ) -> None:
        failures: dict[str, str] = manifest.get("failures", {})
        consecutive = 0
        keys = list(rows)[: self._config.max_details]

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
        self, rows: dict[str, tuple[ListRow, int]], manifest: dict[str, Any]
    ) -> None:
        records: list[dict[str, Any]] = []
        mismatched: list[str] = []
        complete = True
        keys = list(rows)[: self._config.max_details]

        for key in keys:
            row, page_no = rows[key]
            record: dict[str, Any] = {
                "key": key,
                "list": {
                    "scientific_name": row.scientific_name,
                    "trade_name": row.trade_name,
                    "strength": row.strength,
                    "dosage_form": row.dosage_form,
                    "price": row.price,
                    "list_page": page_no,
                },
                "provenance": {
                    "source": SOURCE,
                    "snapshot_id": self._store.run_id,
                    "trust": "official",
                },
            }
            for language in LANGUAGES:
                path = self._store.details_path(language, key)
                if not self._store.has(path):
                    record[language] = None
                    complete = False
                    continue
                stored = self._store.load_page(path)
                fields = parse_details_page(stored.html).fields
                record[language] = [{"label": f.label, "value": f.value} for f in fields]
                record["provenance"][f"{language}_source_ref"] = stored.url
                record["provenance"][f"{language}_fetched_at"] = stored.fetched_at.isoformat()
                if language == "en" and not any(f.value == key for f in fields):
                    mismatched.append(key)
            records.append(record)

        self._counts["records_written"] = self._store.write_records(records)
        manifest["key_not_found_in_details"] = mismatched[:_MAX_RECORDED_ITEMS]
        partial = (
            not complete
            or bool(manifest.get("failures"))
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
