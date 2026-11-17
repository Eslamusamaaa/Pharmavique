"""Crawl any official SFDA table list politely and resumably (list level, no details pages).

It follows the same rules as the drugs crawler: public pages only, robots.txt first, stop on
401/403/429, never store a page that does not parse, progress on disk so a run can be resumed.
The pages are read with `ListWalker`, which copes with the site's repeating last page and unstable
order, and parsed with `parse_generic_page`, which takes the column names from the page itself.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import PageFetcher
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import (
    CrawlError,
    SourceBlocked,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.generic_list import (
    GenericPage,
    GenericRow,
    parse_generic_page,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_walker import ListWalker
from pharmavique.ingestion.infrastructure.connectors.sfda_web.lists import ListSpec
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import ParseError
from pharmavique.ingestion.infrastructure.connectors.sfda_web.polite_fetch import PoliteFetch
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.shared_kernel.ports import Clock

_MAX_RECORDED_ITEMS = 200


@dataclass(frozen=True, slots=True)
class ListCrawlConfig:
    base_url: str = "https://www.sfda.gov.sa"
    max_pages: int | None = None  # limit list pages (sampling)
    retries: int = 3
    retry_wait: float = 30.0
    max_list_passes: int = 8  # first pass plus repair passes (the list order is unstable)
    list_patience: int = 3  # stop after this many repair passes in a row that find nothing new
    user_agent: str = ""  # recorded in the manifest only; the fetcher sends it


class ListCrawler:
    def __init__(
        self,
        *,
        spec: ListSpec,
        fetcher: PageFetcher,
        store: SnapshotStore,
        robots: RobotsPolicy,
        clock: Clock,
        config: ListCrawlConfig | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._spec = spec
        self._store = store
        self._clock = clock
        self._config = config or ListCrawlConfig()
        self._log = logging.getLogger(f"sfda.list.{spec.name}")
        self._counts: dict[str, int] = {}
        self._first_seen_at: dict[str, datetime] = {}
        self._polite = PoliteFetch(
            fetcher,
            robots,
            retries=self._config.retries,
            retry_wait=self._config.retry_wait,
            sleep=sleep,
        )

    async def run(self) -> dict[str, Any]:
        manifest = self._store.load_manifest() or self._new_manifest()
        manifest.setdefault("resumed_at", [])
        if manifest.get("status") not in (None, "new"):
            manifest["resumed_at"].append(self._clock.now().isoformat())
        manifest["status"] = "running"
        manifest["config"] = asdict(self._config)
        self._store.save_manifest(manifest)

        try:
            await self._crawl(manifest)
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

    async def _crawl(self, manifest: dict[str, Any]) -> None:
        walker = ListWalker[GenericRow](
            get_page=self._get_page,
            key_of=lambda row: row.content_key,
            max_pages=self._config.max_pages,
            max_list_pages=self._spec.max_list_pages,
            max_list_passes=self._spec.max_passes(self._config.max_list_passes),
            list_patience=self._config.list_patience,
            log=self._log,
        )
        result = await walker.walk()
        manifest["last_page_in_pager"] = result.hint
        manifest["probed_pages"] = self._spec.probed_pages
        manifest["duplicates"] = result.duplicates[:_MAX_RECORDED_ITEMS]
        if result.expected is not None:
            manifest["list_completeness"] = {
                "expected": result.expected,
                "unique": len(result.known),
                "gap": max(result.expected - len(result.known), 0),
                "passes": result.passes,
            }
        self._counts["list_pages"] = result.page_count
        self._counts["unique_rows"] = len(result.known)
        self._counts["duplicate_rows"] = max(result.total_rows - len(result.known), 0)

        ordered = sorted(result.known.items(), key=lambda item: item[1][1])
        self._counts["records_written"] = self._store.write_records(
            self._record(key, row, page_no) for key, (row, page_no) in ordered
        )
        manifest["status"] = "partial" if self._partial(manifest) else "complete"

    def _partial(self, manifest: dict[str, Any]) -> bool:
        gap = manifest.get("list_completeness", {}).get("gap", 0)
        return gap > 0 or self._config.max_pages is not None

    def _record(self, key: str, row: GenericRow, page_no: int) -> dict[str, Any]:
        fetched_at = self._first_seen_at.get(key)
        return {
            "key": key,
            "entity_key": row.key,
            "list": [{"label": label, "value": value} for label, value in row.cells],
            "link": row.link,
            "list_page": page_no,
            "provenance": {
                "source": self._spec.source,
                "source_ref": self._spec.url(self._config.base_url, page_no),
                "snapshot_id": self._store.run_id,
                "fetched_at": fetched_at.isoformat() if fetched_at else None,
                "trust": "official",
            },
        }

    async def _get_page(self, page_no: int, pass_no: int) -> GenericPage:
        path = self._store.list_page_path(page_no, pass_no)
        if self._store.has(path):
            stored = self._store.load_page(path)
            try:
                parsed = parse_generic_page(stored.html)
            except ParseError:
                self._log.warning("stored page is unreadable, fetching again: %s", path)
            else:
                self._note_first_seen(parsed, stored.fetched_at)
                self._bump("list_pages_reused")
                return parsed
        page, parsed = await self._polite.fetch_valid(
            self._spec.url(self._config.base_url, page_no), parse_generic_page
        )
        self._store.save_page(path, page)
        self._note_first_seen(parsed, page.fetched_at)
        self._bump("list_pages_fetched")
        return parsed

    def _note_first_seen(self, parsed: GenericPage, fetched_at: datetime) -> None:
        for row in parsed.rows:
            self._first_seen_at.setdefault(row.content_key, fetched_at)

    def _bump(self, name: str) -> None:
        self._counts[name] = self._counts.get(name, 0) + 1

    def _new_manifest(self) -> dict[str, Any]:
        return {
            "run_id": self._store.run_id,
            "source": self._spec.source,
            "list": self._spec.name,
            "title": self._spec.title,
            "base_url": self._config.base_url,
            "path": self._spec.path,
            "user_agent": self._config.user_agent,
            "trust": "official",
            "license_status": "unverified, see docs/DATA_SOURCES.md",
            "started_at": self._clock.now().isoformat(),
            "status": "new",
        }
