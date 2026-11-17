"""Media use case: find, judge, download and store pictures of one drug."""

import hashlib
from dataclasses import dataclass
from urllib.parse import quote

from pharmavique.media.application.ports import (
    ImageDownloader,
    ImageRepository,
    ImageSearch,
    ImageStore,
)
from pharmavique.media.domain.images import ImageStatus, ProductImage
from pharmavique.media.domain.matching import (
    ImageCandidate,
    MatchResult,
    MatchVerdict,
    ProductRef,
    build_queries,
    judge,
)
from pharmavique.shared_kernel.ports import Clock
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel

SOURCE = "web-image-search"
MIN_BYTES = 1_000  # smaller than this is an icon or an error body, not a product picture
MAX_BYTES = 5_000_000
RESULTS_PER_QUERY = 10
_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


@dataclass(slots=True)
class FindImagesReport:
    queries: int = 0
    candidates: int = 0
    rejected: int = 0
    download_failed: int = 0
    duplicates: int = 0
    stored: int = 0


@dataclass(frozen=True, slots=True)
class _Found:
    query: str
    candidate: ImageCandidate
    result: MatchResult


class FindProductImagesHandler:
    """For one drug: search the web, keep candidates whose surrounding text names it, download
    the best ones, store them with provenance. Safe to repeat: known pictures are not stored twice.

    A candidate whose text does not even name the drug is never downloaded.
    """

    def __init__(
        self,
        search: ImageSearch,
        downloader: ImageDownloader,
        store: ImageStore,
        repository: ImageRepository,
        clock: Clock,
        *,
        run_id: str,
    ) -> None:
        self._search = search
        self._downloader = downloader
        self._store = store
        self._repository = repository
        self._clock = clock
        self._run_id = run_id

    async def handle(self, product: ProductRef, max_images: int = 3) -> FindImagesReport:
        report = FindImagesReport()
        queries = build_queries(product)
        report.queries = len(queries)
        found = await self._candidates(product, queries, report)

        existing = await self._repository.for_product(product.market, product.register_number)
        known_hashes = {image.content_hash for image in existing}
        known_urls = {image.image_url for image in existing}
        room = max_images - len(existing)

        for item in found:
            if room <= 0:
                break
            if item.candidate.image_url in known_urls:
                report.duplicates += 1
                continue
            image = await self._fetch(product, item, known_hashes, report)
            if image is None:
                continue
            known_hashes.add(image.content_hash)
            known_urls.add(image.image_url)
            await self._repository.add(image)
            report.stored += 1
            room -= 1
        return report

    async def _candidates(
        self, product: ProductRef, queries: tuple[str, ...], report: FindImagesReport
    ) -> list[_Found]:
        seen: set[str] = set()
        found: list[_Found] = []
        for query in queries:
            for candidate in await self._search.search(query, RESULTS_PER_QUERY):
                if candidate.image_url in seen:
                    continue
                seen.add(candidate.image_url)
                report.candidates += 1
                result = judge(product, candidate)
                if result.verdict is MatchVerdict.REJECTED:
                    report.rejected += 1
                    continue
                found.append(_Found(query, candidate, result))
        found.sort(key=lambda f: (f.result.verdict is not MatchVerdict.MATCHED, -f.result.score))
        return found

    async def _fetch(
        self,
        product: ProductRef,
        item: _Found,
        known_hashes: set[str],
        report: FindImagesReport,
    ) -> ProductImage | None:
        downloaded = await self._downloader.download(item.candidate.image_url)
        if (
            downloaded is None
            or not downloaded.content_type.startswith("image/")
            or not MIN_BYTES <= len(downloaded.data) <= MAX_BYTES
        ):
            report.download_failed += 1
            return None
        digest = hashlib.sha256(downloaded.data).hexdigest()
        if digest in known_hashes:
            report.duplicates += 1
            return None

        extension = _EXTENSIONS.get(downloaded.content_type, "img")
        folder = f"products/{product.market.value}/{quote(product.register_number, safe='')}"
        key = f"{folder}/{digest[:16]}.{extension}"
        await self._store.save(key, downloaded.data, downloaded.content_type)
        return ProductImage(
            market=product.market,
            register_number=product.register_number,
            image_url=item.candidate.image_url,
            page_url=item.candidate.page_url,
            query=item.query,
            status=ImageStatus.from_verdict(item.result.verdict),
            score=item.result.score,
            signals=item.result.signals,
            content_hash=digest,
            content_type=downloaded.content_type,
            size_bytes=len(downloaded.data),
            storage_key=key,
            provenance=Provenance(
                SOURCE,
                item.candidate.page_url,
                self._clock.now(),
                self._run_id,
                TrustLevel.UNOFFICIAL_UNVERIFIED,
            ),
        )
