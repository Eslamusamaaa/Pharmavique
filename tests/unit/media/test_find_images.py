"""The picture pipeline on fakes: search, judge, download, store. No network, no files."""

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime

from pharmavique.media.application.handlers import FindProductImagesHandler
from pharmavique.media.application.ports import DownloadedImage
from pharmavique.media.domain.images import ImageStatus, ProductImage
from pharmavique.media.domain.matching import ImageCandidate, ProductRef
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.provenance import TrustLevel

NOW = datetime(2026, 1, 1, tzinfo=UTC)
JPEG = b"\xff\xd8\xff" + b"x" * 2000


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeSearch:
    def __init__(self, results: Mapping[str, list[ImageCandidate]]) -> None:
        self.results = results
        self.queries: list[str] = []

    async def search(self, query: str, limit: int) -> list[ImageCandidate]:
        self.queries.append(query)
        return self.results.get(query, [])[:limit]


class FakeDownloader:
    def __init__(self, files: Mapping[str, DownloadedImage | None]) -> None:
        self.files = files
        self.urls: list[str] = []

    async def download(self, url: str) -> DownloadedImage | None:
        self.urls.append(url)
        return self.files.get(url)


class FakeStore:
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        self.saved[key] = data


class FakeRepository:
    def __init__(self, existing: list[ProductImage] | None = None) -> None:
        self.images = list(existing or [])

    async def for_product(self, market: Market, register_number: str) -> list[ProductImage]:
        return [
            i for i in self.images if i.market is market and i.register_number == register_number
        ]

    async def add(self, image: ProductImage) -> None:
        self.images.append(image)


PRODUCT = ProductRef(
    market=Market.SA,
    register_number="1-111-22",
    trade_name_en="PANADOL Extra",
    trade_name_ar=None,
    ingredient_names=("PARACETAMOL",),
    marketing_company=None,
)
QUERY = "PANADOL Extra PARACETAMOL Saudi Arabia"


def hit(n: int, title: str, host: str = "shop.example.sa") -> ImageCandidate:
    return ImageCandidate(
        image_url=f"https://{host}/img{n}.jpg",
        page_url=f"https://{host}/p{n}",
        title=title,
        alt_text="",
    )


def rig(
    results: Mapping[str, list[ImageCandidate]],
    files: Mapping[str, DownloadedImage | None],
    existing: list[ProductImage] | None = None,
) -> tuple[FindProductImagesHandler, FakeStore, FakeRepository, FakeDownloader]:
    store, repo = FakeStore(), FakeRepository(existing)
    downloader = FakeDownloader(files)
    handler = FindProductImagesHandler(
        FakeSearch(results), downloader, store, repo, FixedClock(), run_id="run-1"
    )
    return handler, store, repo, downloader


def good(n: int) -> DownloadedImage:
    return DownloadedImage(data=JPEG + bytes([n]), content_type="image/jpeg")


async def test_a_matching_picture_is_downloaded_stored_and_recorded_with_provenance() -> None:
    handler, store, repo, _ = rig(
        {QUERY: [hit(1, "Panadol Extra - Saudi Arabia")]},
        {"https://shop.example.sa/img1.jpg": good(1)},
    )

    report = await handler.handle(PRODUCT)

    (image,) = repo.images
    assert report.stored == 1
    assert image.status is ImageStatus.MATCHED
    assert image.content_hash == hashlib.sha256(good(1).data).hexdigest()
    assert store.saved[image.storage_key] == good(1).data
    assert image.provenance.trust is TrustLevel.UNOFFICIAL_UNVERIFIED
    assert image.provenance.source_ref == "https://shop.example.sa/p1"
    assert image.provenance.snapshot_id == "run-1"
    assert image.query == QUERY


async def test_a_rejected_picture_is_never_downloaded() -> None:
    handler, _, repo, downloader = rig(
        {QUERY: [hit(1, "Some other medicine, Saudi Arabia")]},
        {"https://shop.example.sa/img1.jpg": good(1)},
    )

    report = await handler.handle(PRODUCT)

    assert downloader.urls == []
    assert repo.images == []
    assert report.rejected == 1


async def test_a_picture_without_saudi_evidence_is_kept_for_review_not_published() -> None:
    handler, _, repo, _ = rig(
        {QUERY: [hit(1, "Panadol Extra caplets", host="example.com")]},
        {"https://example.com/img1.jpg": good(1)},
    )

    await handler.handle(PRODUCT)

    assert [i.status for i in repo.images] == [ImageStatus.NEEDS_REVIEW]
    assert all(not i.publishable for i in repo.images)


async def test_matched_pictures_are_preferred_and_the_number_is_capped() -> None:
    results = {
        QUERY: [
            hit(1, "Panadol Extra caplets", host="example.com"),
            hit(2, "Panadol Extra Saudi Arabia"),
            hit(3, "Panadol Extra saudi pharmacy"),
            hit(4, "Panadol Extra KSA"),
        ]
    }
    files = {f"https://shop.example.sa/img{n}.jpg": good(n) for n in range(2, 5)}
    files["https://example.com/img1.jpg"] = good(1)
    handler, _, repo, _ = rig(results, files)

    await handler.handle(PRODUCT, max_images=2)

    assert len(repo.images) == 2
    assert all(i.status is ImageStatus.MATCHED for i in repo.images)


async def test_the_same_picture_found_twice_or_already_stored_is_kept_once() -> None:
    results = {
        QUERY: [hit(1, "Panadol Extra Saudi"), hit(2, "Panadol Extra Saudi")],
        "PANADOL Extra Saudi Arabia": [hit(1, "Panadol Extra Saudi")],
    }
    same = good(1)
    files = {"https://shop.example.sa/img1.jpg": same, "https://shop.example.sa/img2.jpg": same}
    handler, _, repo, _ = rig(results, files)

    await handler.handle(PRODUCT)
    await handler.handle(PRODUCT)

    assert len(repo.images) == 1


async def test_a_download_that_fails_or_is_not_an_image_is_skipped() -> None:
    results = {QUERY: [hit(1, "Panadol Extra Saudi"), hit(2, "Panadol Extra Saudi")]}
    files: dict[str, DownloadedImage | None] = {
        "https://shop.example.sa/img1.jpg": None,
        "https://shop.example.sa/img2.jpg": DownloadedImage(b"<html>", "text/html"),
    }
    handler, _, repo, _ = rig(results, files)

    report = await handler.handle(PRODUCT)

    assert repo.images == []
    assert report.download_failed == 2


async def test_a_tiny_or_huge_file_is_not_accepted_as_a_product_picture() -> None:
    results = {QUERY: [hit(1, "Panadol Extra Saudi"), hit(2, "Panadol Extra Saudi")]}
    files: dict[str, DownloadedImage | None] = {
        "https://shop.example.sa/img1.jpg": DownloadedImage(b"\xff\xd8\xff", "image/jpeg"),
        "https://shop.example.sa/img2.jpg": DownloadedImage(b"x" * 6_000_000, "image/jpeg"),
    }
    handler, _, repo, _ = rig(results, files)

    await handler.handle(PRODUCT)

    assert repo.images == []


async def test_a_product_with_no_name_makes_no_search() -> None:
    nameless = ProductRef(Market.SA, "9-9", None, None, ("X",), None)
    handler, _, repo, _ = rig({}, {})

    report = await handler.handle(nameless)

    assert report.queries == 0
    assert repo.images == []
