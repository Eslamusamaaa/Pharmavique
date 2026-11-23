"""Downloading the pictures of listings, with fakes for the site, the disk and the database."""

from datetime import UTC, datetime
from pathlib import Path

from pharmavique.offers.application.images import DownloadImages, PendingImage
from pharmavique.offers.application.ports import FetchFailed, FetchResult, SourceBlocked
from pharmavique.offers.domain.model import RunStatus
from pharmavique.offers.infrastructure.images import DiskImageSink

NOW = datetime(2026, 11, 23, tzinfo=UTC)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 400


class Store:
    def __init__(self, pending: list[PendingImage]) -> None:
        self.pending = pending
        self.recorded: dict[int, tuple[str, str | None]] = {}

    async def pending_images(self, limit: int) -> list[PendingImage]:
        return [p for p in self.pending if p.listing_id not in self.recorded][:limit]

    async def record(
        self,
        image: PendingImage,
        status: str,
        file_path: str | None,
        sha256: str | None,
        size: int | None,
        content_type: str | None,
        now: datetime,
    ) -> None:
        self.recorded[image.listing_id] = (status, file_path)


class Fetcher:
    def __init__(self, answers: dict[str, FetchResult | Exception]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    async def get(self, url: str) -> FetchResult:
        self.asked.append(url)
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Sink:
    def __init__(self) -> None:
        self.saved: list[str] = []

    def save(self, retailer_id: str, content: bytes, content_type: str) -> tuple[str, str]:
        self.saved.append(retailer_id)
        return f"{retailer_id}/ab/abcd.png", "abcd"


def image(listing_id: int, url: str) -> PendingImage:
    return PendingImage(listing_id, 0, "nahdi", url)


def ok(content: bytes = PNG) -> FetchResult:
    return FetchResult(200, content)


def result_for(content_type: str, content: bytes = PNG) -> FetchResult:
    return FetchResult(200, content, content_type=content_type)


async def run(pending, answers, limit=100):
    store, sink = Store(pending), Sink()

    async def fetcher_for(host: str) -> Fetcher:
        return Fetcher(answers)

    use = DownloadImages(store, fetcher_for, sink, lambda: NOW)
    return store, sink, await use.run(limit)


async def test_a_picture_is_downloaded_saved_and_recorded() -> None:
    answers = {"https://c/1.png": result_for("image/png")}

    store, sink, report = await run([image(1, "https://c/1.png")], answers)

    assert store.recorded == {1: ("ok", "nahdi/ab/abcd.png")}
    assert sink.saved == ["nahdi"]
    assert report.status is RunStatus.COMPLETE
    assert report.counters["ok"] == 1


async def test_a_page_that_is_not_a_picture_is_recorded_and_not_saved() -> None:
    answers = {"https://c/1.png": result_for("text/html", b"<html>nope</html>" * 40)}

    store, sink, _ = await run([image(1, "https://c/1.png")], answers)

    assert store.recorded == {1: ("not_an_image", None)}
    assert sink.saved == []


async def test_a_tiny_answer_is_not_a_picture() -> None:
    answers = {"https://c/1.png": result_for("image/png", b"x" * 20)}

    store, _, _ = await run([image(1, "https://c/1.png")], answers)

    assert store.recorded[1][0] == "not_an_image"


async def test_a_missing_picture_is_gone_and_a_failed_one_is_failed() -> None:
    answers: dict[str, FetchResult | Exception] = {
        "https://c/1.png": FetchResult(404, b""),
        "https://c/2.png": FetchFailed("boom"),
    }

    store, _, report = await run(
        [image(1, "https://c/1.png"), image(2, "https://c/2.png")], answers
    )

    assert store.recorded == {1: ("gone", None), 2: ("failed", None)}
    assert report.status is RunStatus.PARTIAL


async def test_a_block_ends_the_run_and_the_rest_stays_pending() -> None:
    answers: dict[str, FetchResult | Exception] = {
        "https://c/1.png": SourceBlocked("HTTP 403"),
        "https://c/2.png": result_for("image/png"),
    }

    store, _, report = await run(
        [image(1, "https://c/1.png"), image(2, "https://c/2.png")], answers
    )

    assert report.status is RunStatus.BLOCKED
    assert store.recorded == {}


async def test_the_limit_stops_the_run_early() -> None:
    answers = {f"https://c/{i}.png": result_for("image/png") for i in range(5)}

    store, _, report = await run([image(i, f"https://c/{i}.png") for i in range(5)], answers, 2)

    assert len(store.recorded) == 2
    assert report.status is RunStatus.PARTIAL


def test_a_picture_is_stored_by_its_content_so_two_copies_are_one_file(tmp_path: Path) -> None:
    sink = DiskImageSink(tmp_path)

    first, digest = sink.save("nahdi", PNG, "image/png")
    second, same = sink.save("nahdi", PNG, "image/png")

    assert first == second
    assert digest == same
    assert (tmp_path / first).read_bytes() == PNG
    assert first.endswith(".png")
    assert sum(1 for p in tmp_path.rglob("*") if p.is_file()) == 1
