"""Restoring pictures: download again, keep only bytes that match the recorded hash."""

import hashlib

from pharmavique.media.application.ports import DownloadedImage
from pharmavique.media.application.restore import ImageRestorer, WantedImage

GOOD = b"\xff\xd8\xff" + b"a" * 2000
OTHER = b"\xff\xd8\xff" + b"b" * 2000


def wanted(key: str, url: str, data: bytes = GOOD) -> WantedImage:
    return WantedImage(key, url, hashlib.sha256(data).hexdigest())


class FakeDownloader:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.asked: list[str] = []

    async def download(self, url: str) -> DownloadedImage | None:
        self.asked.append(url)
        data = self.files.get(url)
        return None if data is None else DownloadedImage(data, "image/jpeg")


class MemoryStore:
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        self.saved[key] = data


async def test_a_missing_picture_is_downloaded_and_stored() -> None:
    store = MemoryStore()
    restorer = ImageRestorer(FakeDownloader({"u1": GOOD}), store, lambda key: False)

    report = await restorer.run([wanted("p/1.jpg", "u1")])

    assert store.saved == {"p/1.jpg": GOOD}
    assert report.restored == 1


async def test_a_picture_that_is_already_on_disk_is_not_downloaded_again() -> None:
    downloader = FakeDownloader({"u1": GOOD})
    restorer = ImageRestorer(downloader, MemoryStore(), lambda key: True)

    report = await restorer.run([wanted("p/1.jpg", "u1")])

    assert downloader.asked == []
    assert report.already_there == 1


async def test_bytes_that_no_longer_match_the_recorded_hash_are_not_kept() -> None:
    store = MemoryStore()
    restorer = ImageRestorer(FakeDownloader({"u1": OTHER}), store, lambda key: False)

    report = await restorer.run([wanted("p/1.jpg", "u1", GOOD)])

    assert store.saved == {}
    assert report.changed == ["p/1.jpg"]


async def test_a_picture_the_shop_does_not_give_back_is_reported() -> None:
    restorer = ImageRestorer(FakeDownloader({}), MemoryStore(), lambda key: False)

    report = await restorer.run([wanted("p/1.jpg", "gone")])

    assert report.unavailable == ["p/1.jpg"]


async def test_the_same_key_is_fetched_once() -> None:
    downloader = FakeDownloader({"u1": GOOD})
    restorer = ImageRestorer(downloader, MemoryStore(), lambda key: False)

    await restorer.run([wanted("p/1.jpg", "u1"), wanted("p/1.jpg", "u1")])

    assert downloader.asked == ["u1"]
