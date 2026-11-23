"""Download the main picture of every listing, once, as a file.

Resumable: a picture already recorded (saved, gone, failed or not a picture) is not asked for again.
A block ends the run at once and the remaining pictures stay pending; nothing is ever retried after
a block. One host may be a CDN other than the shop, so each picture is fetched through the polite
fetcher of its own host.
"""

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse

from pharmavique.offers.application.crawl import CrawlReport
from pharmavique.offers.application.ports import FetchFailed, PageFetcher, SourceBlocked
from pharmavique.offers.domain.model import RunStatus

__all__ = ["DownloadImages", "ImageSink", "ImageStore", "PendingImage"]

MIN_BYTES = 200  # anything smaller is an error page, not a picture


@dataclass(frozen=True, slots=True)
class PendingImage:
    listing_id: int
    position: int
    retailer_id: str
    url: str


class ImageStore(Protocol):
    async def pending_images(self, limit: int) -> list[PendingImage]: ...

    async def record(
        self,
        image: PendingImage,
        status: str,
        file_path: str | None,
        sha256: str | None,
        size: int | None,
        content_type: str | None,
        now: datetime,
    ) -> None: ...


class ImageSink(Protocol):
    def save(self, retailer_id: str, content: bytes, content_type: str) -> tuple[str, str]:
        """Write the picture; returns (path relative to the picture folder, sha256)."""
        ...


class DownloadImages:
    def __init__(
        self,
        store: ImageStore,
        fetcher_for: Callable[[str], Awaitable[PageFetcher]],
        sink: ImageSink,
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._fetcher_for = fetcher_for
        self._sink = sink
        self._now = now

    async def run(self, limit: int) -> CrawlReport:
        pending = await self._store.pending_images(limit + 1)
        counts: Counter[str] = Counter()
        blocked = False
        done = 0
        for image in pending[:limit]:
            try:
                await self._one(image, counts)
            except SourceBlocked:
                blocked = True
                break
            done += 1
        counts["remaining"] = len(pending) - done
        if blocked:
            status = RunStatus.BLOCKED
        elif counts["remaining"] or counts["failed"]:
            status = RunStatus.PARTIAL
        else:
            status = RunStatus.COMPLETE
        return CrawlReport(status, dict(counts))

    async def _one(self, image: PendingImage, counts: Counter[str]) -> None:
        fetcher = await self._fetcher_for(urlparse(image.url).netloc)
        now = self._now()
        try:
            result = await fetcher.get(image.url)
        except FetchFailed:
            await self._store.record(image, "failed", None, None, None, None, now)
            counts["failed"] += 1
            return
        if result.status in (404, 410):
            await self._store.record(image, "gone", None, None, None, None, now)
            counts["gone"] += 1
            return
        kind = (result.content_type or "").split(";")[0].strip().lower()
        if result.status != 200 or not kind.startswith("image/") or len(result.content) < MIN_BYTES:
            await self._store.record(image, "not_an_image", None, None, None, kind or None, now)
            counts["not_an_image"] += 1
            return
        path, digest = self._sink.save(image.retailer_id, result.content, kind)
        await self._store.record(image, "ok", path, digest, len(result.content), kind, now)
        counts["ok"] += 1
