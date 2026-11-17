"""Plain-file adapters for the image store and the image records. Real files, no network."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pharmavique.media.domain.images import ImageStatus, ProductImage
from pharmavique.media.infrastructure.files import (
    FileImageStore,
    JsonlAttemptLog,
    JsonlImageRepository,
)
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel


def image(number: str = "1-1", digest: str = "ab" * 32) -> ProductImage:
    return ProductImage(
        market=Market.SA,
        register_number=number,
        image_url="https://shop.example.sa/i.jpg",
        page_url="https://shop.example.sa/p",
        query="q",
        status=ImageStatus.MATCHED,
        score=0.85,
        signals=("name", "saudi"),
        content_hash=digest,
        content_type="image/jpeg",
        size_bytes=2048,
        storage_key=f"products/SA/{number}/{digest[:16]}.jpg",
        provenance=Provenance(
            "web-image-search",
            "https://shop.example.sa/p",
            datetime(2026, 1, 1, tzinfo=UTC),
            "run-1",
            TrustLevel.UNOFFICIAL_UNVERIFIED,
        ),
    )


async def test_the_store_writes_bytes_under_its_key(tmp_path: Path) -> None:
    store = FileImageStore(tmp_path)

    await store.save("products/SA/1-1/abc.jpg", b"data", "image/jpeg")

    assert (tmp_path / "products" / "SA" / "1-1" / "abc.jpg").read_bytes() == b"data"


@pytest.mark.parametrize("key", ["../escape.jpg", "/abs/path.jpg", "a/../../b.jpg"])
async def test_a_key_that_leaves_the_store_folder_is_refused(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="key"):
        await FileImageStore(tmp_path).save(key, b"x", "image/jpeg")


async def test_records_survive_a_restart_and_come_back_equal(tmp_path: Path) -> None:
    path = tmp_path / "images.jsonl"
    await JsonlImageRepository(path).add(image("1-1"))
    await JsonlImageRepository(path).add(image("2-2", "cd" * 32))

    again = JsonlImageRepository(path)

    assert await again.for_product(Market.SA, "1-1") == [image("1-1")]
    assert await again.for_product(Market.SA, "2-2") == [image("2-2", "cd" * 32)]
    assert await again.for_product(Market.SA, "9-9") == []


async def test_a_half_written_last_line_is_ignored_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "images.jsonl"
    await JsonlImageRepository(path).add(image("1-1"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"market": "SA", "register_n')

    assert len(await JsonlImageRepository(path).for_product(Market.SA, "1-1")) == 1


def test_the_attempt_log_remembers_which_products_were_tried_across_restarts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "attempts.jsonl"
    log = JsonlAttemptLog(path)
    log.record(Market.SA, "1-1", stored=2, at=datetime(2026, 1, 1, tzinfo=UTC))
    log.record(Market.SA, "2-2", stored=0, at=datetime(2026, 1, 1, tzinfo=UTC))

    again = JsonlAttemptLog(path)

    assert again.was_tried(Market.SA, "1-1")
    assert again.was_tried(Market.SA, "2-2")
    assert not again.was_tried(Market.SA, "3-3")
    assert again.tried_count == 2


def test_a_half_written_attempt_line_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    JsonlAttemptLog(path).record(Market.SA, "1-1", stored=1, at=datetime(2026, 1, 1, tzinfo=UTC))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"market": "SA", "regi')

    assert JsonlAttemptLog(path).was_tried(Market.SA, "1-1")
