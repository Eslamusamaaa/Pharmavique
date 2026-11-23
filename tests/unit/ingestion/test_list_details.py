"""Detail pages of SFDA lists, on synthetic pages: nothing touches the network."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import SourceBlocked
from pharmavique.ingestion.infrastructure.connectors.sfda_web.list_details import (
    ListDetailCrawler,
    parse_detail_page,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import ParseError

NOW = datetime(2026, 1, 1, tzinfo=UTC)

SHORTAGE = (
    "<table><tr><td>Trade name</td><td>Hyrimoz</td></tr>"
    "<tr><td>Trade name</td><td>Abrilada</td></tr></table>"
)
APPROVAL = (
    "<table><thead><tr><th>SFDA Approved Use</th></tr></thead>"
    "<tbody><tr><td>Lurasidone is indicated for:<br>Schizophrenia in adults.</td></tr>"
    "</tbody></table>"
)


def test_a_two_cell_row_is_a_label_value_pair() -> None:
    assert parse_detail_page(SHORTAGE).pairs == (
        ("Trade name", "Hyrimoz"),
        ("Trade name", "Abrilada"),
    )


def test_a_one_cell_row_takes_the_table_header_as_its_label() -> None:
    assert parse_detail_page(APPROVAL).pairs == (
        ("SFDA Approved Use", "Lurasidone is indicated for:\nSchizophrenia in adults."),
    )


def test_a_page_without_a_table_or_values_is_not_accepted() -> None:
    with pytest.raises(ParseError):
        parse_detail_page("<p>nothing</p>")
    with pytest.raises(ParseError):
        parse_detail_page("<table><tr><td>Trade name</td><td></td></tr></table>")


class FakeFetcher:
    def __init__(self, status: int = 200) -> None:
        self.calls: list[str] = []
        self.status = status

    async def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        return FetchedPage(url, self.status, SHORTAGE, NOW)


async def no_sleep(_: float) -> None:
    return None


def records() -> list[dict[str, object]]:
    return [
        {"key": "A#1", "link": "/en/details_data?id=A"},
        {"key": "B#2", "link": None},
        {"key": "C#3", "link": "/en/details_data?id=C"},
    ]


def crawler(fetcher: FakeFetcher, robots: str = "") -> ListDetailCrawler:
    return ListDetailCrawler(
        fetcher=fetcher,
        robots=RobotsPolicy.from_text(robots, "test"),
        base_url="https://sfda.test",
        retry_wait=0.0,
        sleep=no_sleep,
    )


async def test_only_rows_with_a_link_are_fetched_and_a_rerun_fetches_nothing(
    tmp_path: Path,
) -> None:
    fetcher = FakeFetcher()
    out = tmp_path / "details.jsonl"
    first = await crawler(fetcher).run(records(), out)
    assert first == {"stored_before": 0, "fetched": 2, "failed": 0}
    stored = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [row["key"] for row in stored] == ["A#1", "C#3"]
    assert stored[0]["detail"][0] == {"label": "Trade name", "value": "Hyrimoz"}
    assert stored[0]["source_ref"] == "https://sfda.test/en/details_data?id=A"

    again = await crawler(fetcher).run(records(), out)
    assert again == {"stored_before": 2, "fetched": 0, "failed": 0}
    assert len(fetcher.calls) == 2


async def test_a_block_stops_the_run_and_robots_is_honoured(tmp_path: Path) -> None:
    with pytest.raises(SourceBlocked):
        await crawler(FakeFetcher(status=429)).run(records(), tmp_path / "d.jsonl")
    fetcher = FakeFetcher()
    with pytest.raises(SourceBlocked):
        await crawler(fetcher, "User-agent: *\nDisallow: /en/details_data").run(
            records(), tmp_path / "e.jsonl"
        )
    assert fetcher.calls == []


NODE = """
<main><div class="text"><h2 class="mb-3 fs-3">Voluntary Recall of two batches of Dopram</h2>
<span>2026-02-12</span>
<div class="node__content">
<div class="text-formatted field field--name-body field--label-hidden field__item">
 Trade Name Scientific Name Register Number Dopram DOXAPRAM</div>
<div class="field field--name-field-date field--label-above">
 <div class="field__label">التاريخ</div><div class="field__item">2025-11-02</div></div>
<div class="field field--name-field-issue field--label-above">
 <div class="field__label">سبب السحب</div>
 <div class="field__item"><p><span>Non-compliance with specifications.</span></p></div></div>
<div class="field field--name-field-file-media field--label-hidden field__items">
 <a href="/sites/default/files/2025-11/Dopram.pdf">Letter</a></div>
</div></div></main>
"""


def test_a_page_without_a_table_is_read_from_its_labelled_fields() -> None:
    pairs = dict(parse_detail_page(NODE).pairs)
    assert pairs["Title"] == "Voluntary Recall of two batches of Dopram"
    assert pairs["التاريخ"] == "2025-11-02"
    assert pairs["سبب السحب"] == "Non-compliance with specifications."
    assert pairs["Body"].startswith("Trade Name Scientific Name")
    assert pairs["Attachment"] == "/sites/default/files/2025-11/Dopram.pdf"


async def test_links_to_documents_are_left_to_the_files_step(tmp_path: Path) -> None:
    fetcher = FakeFetcher()
    rows = [
        {"key": "A#1", "link": "/sites/default/files/2026-10/Safety%20Signal.pdf"},
        {"key": "B#2", "link": "/sites/default/files/x.DOCX"},
        {"key": "C#3", "link": "/en/details_data?id=C"},
    ]

    counts = await crawler(fetcher).run(rows, tmp_path / "details.jsonl")

    assert fetcher.calls == ["https://sfda.test/en/details_data?id=C"]
    assert counts == {"stored_before": 0, "fetched": 1, "failed": 0, "documents": 2}


async def test_details_of_an_earlier_run_are_reused_and_only_new_rows_are_fetched(
    tmp_path: Path,
) -> None:
    earlier = tmp_path / "earlier.jsonl"
    await crawler(FakeFetcher()).run(records(), earlier)

    fetcher = FakeFetcher()
    new_records: list[dict[str, object]] = [
        *records(),
        {"key": "D#4", "link": "/en/details_data?id=D"},
    ]
    out = tmp_path / "details.jsonl"
    counts = await crawler(fetcher).run(new_records, out, reuse_from=earlier)

    assert counts == {"stored_before": 0, "reused": 2, "fetched": 1, "failed": 0}
    assert fetcher.calls == ["https://sfda.test/en/details_data?id=D"]
    stored = [json.loads(line)["key"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert stored == ["A#1", "C#3", "D#4"]


async def test_a_row_that_left_the_list_is_not_carried_over(tmp_path: Path) -> None:
    earlier = tmp_path / "earlier.jsonl"
    await crawler(FakeFetcher()).run(records(), earlier)

    out = tmp_path / "details.jsonl"
    await crawler(FakeFetcher()).run(records()[:1], out, reuse_from=earlier)

    stored = [json.loads(line)["key"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert stored == ["A#1"]
