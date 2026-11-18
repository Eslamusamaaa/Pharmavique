"""Documents behind SFDA list rows, on a mock server: nothing touches the network."""

import json
from pathlib import Path

import httpx
import pytest

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import SourceBlocked
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_files import (
    ListFileCrawler,
    is_document_link,
)

PDF = b"%PDF-1.4 safety signal"


def test_only_links_to_documents_are_followed() -> None:
    assert is_document_link("/sites/default/files/2026-10/Signal%20X.pdf")
    assert is_document_link("/sites/default/files/a.DOCX")
    assert not is_document_link("/en/details_data?id=A")
    assert not is_document_link(None)


def records() -> list[dict[str, object]]:
    return [
        {"key": "A#1", "link": "/sites/default/files/a.pdf"},
        {"key": "B#2", "link": "/en/news/2"},
        {"key": "C#3", "link": "/sites/default/files/c.pdf"},
    ]


def crawler(handler: httpx.MockTransport, robots: str = "") -> tuple[ListFileCrawler, list[str]]:
    seen: list[str] = []

    def record_and_answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler.handle_request(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record_and_answer))
    made = ListFileCrawler(
        client=client,
        robots=RobotsPolicy.from_text(robots, "test"),
        throttle=Throttle(0.0, 0.0),
        base_url="https://sfda.test",
    )
    return made, seen


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})


async def test_documents_are_stored_by_hash_and_a_rerun_downloads_nothing(tmp_path: Path) -> None:
    made, seen = crawler(httpx.MockTransport(ok))
    index = tmp_path / "files.jsonl"
    first = await made.run(records(), tmp_path / "files", index)
    assert first == {"stored_before": 0, "downloaded": 2, "failed": 0}
    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
    assert [row["key"] for row in rows] == ["A#1", "C#3"]
    assert (tmp_path / "files" / rows[0]["file"]).read_bytes() == PDF
    assert rows[0]["source_ref"] == "https://sfda.test/sites/default/files/a.pdf"

    again, _ = crawler(httpx.MockTransport(ok))
    assert await again.run(records(), tmp_path / "files", index) == {
        "stored_before": 2,
        "downloaded": 0,
        "failed": 0,
    }
    assert len(seen) == 2


async def test_an_html_answer_is_not_kept_as_a_document(tmp_path: Path) -> None:
    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"<html>blocked</html>", headers={"content-type": "text/html"}
        )

    made, _ = crawler(httpx.MockTransport(html))
    counts = await made.run(records(), tmp_path / "f", tmp_path / "i.jsonl")
    assert counts == {"stored_before": 0, "downloaded": 0, "failed": 2}


async def test_a_web_page_sent_with_a_document_type_is_not_kept(tmp_path: Path) -> None:
    """The homepage once came back as a "docx": the type said document, the bytes were HTML."""

    def page_as_docx(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<!DOCTYPE html>\r\n<html><body>Home</body></html>",
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml"
            },
        )

    made, _ = crawler(httpx.MockTransport(page_as_docx))
    counts = await made.run(records(), tmp_path / "f", tmp_path / "i.jsonl")
    assert counts == {"stored_before": 0, "downloaded": 0, "failed": 2}


async def test_a_block_stops_the_run_and_robots_is_honoured(tmp_path: Path) -> None:
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    made, _ = crawler(httpx.MockTransport(blocked))
    with pytest.raises(SourceBlocked):
        await made.run(records(), tmp_path / "f", tmp_path / "i.jsonl")

    made, seen = crawler(httpx.MockTransport(ok), "User-agent: *\nDisallow: /sites/")
    with pytest.raises(SourceBlocked):
        await made.run(records(), tmp_path / "g", tmp_path / "j.jsonl")
    assert seen == []
