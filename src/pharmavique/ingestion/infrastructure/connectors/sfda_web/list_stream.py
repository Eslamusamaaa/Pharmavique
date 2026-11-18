"""Crawl a giant SFDA list (hundreds of thousands of pages) without holding it in memory.

`ListCrawler` keeps every row of a list in memory so it can repair the site's unstable order with
extra passes. That is fine for thousands of rows and impossible for the 1.5 and 3 million row lists.
This crawler writes each page's rows to `records.jsonl` as soon as the page is read and remembers
only a 64-bit fingerprint of each row (to drop repeats). Differences from `ListCrawler`:

- a single pass, no repair passes: a few rows may be missed or repeated because the list order is
  unstable (`list_completeness` says how many rows were read and how many were repeats);
- resumable at page level: a stopped crawl continues at the last page it wrote;
- the same rules otherwise: public pages only, robots.txt first, stop on 401/403/429, nothing stored
  that does not parse.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
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
    parse_generic_page,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_crawler import (
    ListCrawlConfig,
    build_record,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_walker import is_end_of_list
from pharmavique.ingestion.infrastructure.connectors.sfda_web.lists import ListSpec
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import ParseError
from pharmavique.ingestion.infrastructure.connectors.sfda_web.polite_fetch import PoliteFetch
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
from pharmavique.shared_kernel.ports import Clock

_CHECKPOINT_EVERY = 100  # pages


def _fingerprint(key: str) -> int:
    return int.from_bytes(hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest(), "big")


class StreamingListCrawler:
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
        self._log = logging.getLogger(f"sfda.stream.{spec.name}")
        self._polite = PoliteFetch(
            fetcher,
            robots,
            retries=self._config.retries,
            retry_wait=self._config.retry_wait,
            sleep=sleep,
        )
        self._fetched = 0  # pages fetched since the last checkpoint
        self._duplicates = 0  # repeated rows seen in this run

    async def run(self) -> dict[str, Any]:
        manifest = self._store.load_manifest() or self._new_manifest()
        manifest.setdefault("resumed_at", [])
        if manifest.get("status") not in (None, "new"):
            manifest["resumed_at"].append(self._clock.now().isoformat())
        manifest["status"] = "running"
        manifest["config"] = asdict(self._config)
        manifest["mode"] = "streaming, single pass"
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
            manifest["finished_at"] = self._clock.now().isoformat()
            self._store.save_manifest(manifest)
        return manifest

    async def _crawl(self, manifest: dict[str, Any]) -> None:
        known, page_no, earlier_duplicates = self._resume(manifest)
        hint: int | None = manifest.get("last_page_in_pager")
        ended = False

        while self._config.max_pages is None or page_no < self._config.max_pages:
            if page_no >= self._spec.max_list_pages:
                raise CrawlError(f"the list has more than {self._spec.max_list_pages} pages")
            parsed, fetched_at = await self._get_page(page_no)
            if page_no == 0:
                hint = parsed.last_page
                manifest["last_page_in_pager"] = hint
            if is_end_of_list(parsed, page_no, hint):
                ended = True
                manifest["last_page"] = page_no - 1
                break
            self._write_rows(parsed, page_no, fetched_at, known)
            page_no += 1
            if page_no % _CHECKPOINT_EVERY == 0:
                self._checkpoint(manifest, page_no, known, earlier_duplicates)
                self._log.info("page %s of about %s: %s rows", page_no, hint, len(known))

        self._checkpoint(manifest, page_no, known, earlier_duplicates)
        repeats = earlier_duplicates + self._duplicates
        manifest["list_completeness"] = {
            "rows_read": len(known) + repeats,
            "unique": len(known),
            "repeats": repeats,
            "passes": 1,
        }
        manifest["status"] = "complete" if ended and self._config.max_pages is None else "partial"

    def _write_rows(
        self, parsed: GenericPage, page_no: int, fetched_at: datetime, known: set[int]
    ) -> None:
        fresh: list[dict[str, Any]] = []
        for row in parsed.rows:
            key = row.content_key
            fingerprint = _fingerprint(key)
            if fingerprint in known:
                self._duplicates += 1
                continue
            known.add(fingerprint)
            fresh.append(
                build_record(
                    spec=self._spec,
                    base_url=self._config.base_url,
                    run_id=self._store.run_id,
                    key=key,
                    row=row,
                    page_no=page_no,
                    fetched_at=fetched_at,
                )
            )
        self._store.append_records(fresh)

    def _checkpoint(
        self, manifest: dict[str, Any], page_no: int, known: set[int], earlier_duplicates: int
    ) -> None:
        manifest["next_page"] = page_no
        counts = manifest.get("counts", {})
        manifest["counts"] = {
            "list_pages_fetched": int(counts.get("list_pages_fetched", 0)) + self._fetched,
            "unique_rows": len(known),
            "duplicate_rows": earlier_duplicates + self._duplicates,
        }
        self._fetched = 0
        self._store.save_manifest(manifest)

    def _resume(self, manifest: dict[str, Any]) -> tuple[set[int], int, int]:
        """Fingerprints of the rows already written, the page to continue at, earlier repeats.

        The last written page is read again (from its stored copy): a crash may have left it half
        written, and rows already on disk are recognised as repeats and skipped.
        """
        known: set[int] = set()
        last_page = 0
        path = self._store.records_path
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                        key, page = record["key"], int(record["list_page"])
                    except (ValueError, KeyError):
                        continue  # a half-written last line
                    known.add(_fingerprint(key))
                    last_page = max(last_page, page)
        earlier = int(manifest.get("counts", {}).get("duplicate_rows", 0))
        return known, last_page, earlier

    async def _get_page(self, page_no: int) -> tuple[GenericPage, datetime]:
        path = self._store.list_page_path(page_no)
        if self._store.has(path):
            stored = self._store.load_page(path)
            try:
                return parse_generic_page(stored.html), stored.fetched_at
            except ParseError:
                self._log.warning("stored page is unreadable, fetching again: %s", path)
        page, parsed = await self._polite.fetch_valid(
            self._spec.url(self._config.base_url, page_no), parse_generic_page
        )
        self._store.save_page(path, page)
        self._fetched += 1
        return parsed, page.fetched_at

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
