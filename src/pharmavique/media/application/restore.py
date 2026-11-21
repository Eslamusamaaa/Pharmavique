"""Bring back stored product pictures whose files are gone (a machine move, a cleaned folder).

`images.jsonl` remembers where every picture came from (its URL) and the sha256 of its bytes. A
missing file is downloaded again from that URL, politely, and kept only if the bytes hash to the
recorded value: a shop that changed the picture must not slip a different box under an old
verification.
"""

import asyncio
import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from pharmavique.media.application.ports import ImageDownloader, ImageStore


@dataclass(frozen=True, slots=True)
class WantedImage:
    storage_key: str
    image_url: str
    content_hash: str  # sha256 recorded when the picture was first stored


@dataclass(slots=True)
class RestoreReport:
    restored: int = 0
    already_there: int = 0
    unavailable: list[str] = field(default_factory=list)  # keys the shop did not give back
    changed: list[str] = field(default_factory=list)  # keys whose bytes no longer match


class ImageRestorer:
    def __init__(
        self,
        downloader: ImageDownloader,
        store: ImageStore,
        exists: Callable[[str], bool],
        *,
        concurrency: int = 12,
    ) -> None:
        self._downloader = downloader
        self._store = store
        self._exists = exists
        self._gate = asyncio.Semaphore(concurrency)

    async def run(
        self,
        wanted: Iterable[WantedImage],
        progress: Callable[[RestoreReport], None] | None = None,
    ) -> RestoreReport:
        report = RestoreReport()
        unique = {item.storage_key: item for item in wanted}
        await asyncio.gather(*(self._one(item, report, progress) for item in unique.values()))
        return report

    async def _one(
        self,
        item: WantedImage,
        report: RestoreReport,
        progress: Callable[[RestoreReport], None] | None,
    ) -> None:
        if self._exists(item.storage_key):
            report.already_there += 1
            return
        async with self._gate:
            image = await self._downloader.download(item.image_url)
        if image is None:
            report.unavailable.append(item.storage_key)
        elif hashlib.sha256(image.data).hexdigest() != item.content_hash:
            report.changed.append(item.storage_key)
        else:
            await self._store.save(item.storage_key, image.data, image.content_type)
            report.restored += 1
        if progress is not None:
            progress(report)
