"""Official documents read from the stored SFDA list runs (records, details and texts)."""

import json
from pathlib import Path

from pharmavique.knowledge.infrastructure.list_documents import StoredListDocuments


def write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def record(key: str, cells: list[tuple[str, str]], link: str | None = None) -> dict[str, object]:
    return {
        "key": key,
        "entity_key": key,
        "link": link,
        "list": [{"label": k, "value": v} for k, v in cells],
        "list_page": 0,
        "provenance": {
            "fetched_at": "2026-11-18T10:00:00+00:00",
            "snapshot_id": "lists-1",
            "source": "sfda-list-x",
            "source_ref": "https://www.sfda.gov.sa/en/list?page=0",
            "trust": "official",
        },
    }


def test_a_row_with_a_document_text_uses_that_text_and_its_file(tmp_path: Path) -> None:
    run = tmp_path / "dhpc" / "lists-1"
    write(
        run / "records.jsonl",
        [
            record(
                "A#1",
                [
                    ("Product", "Gilenya (fingolimod)"),
                    ("Date", "2021-01-10"),
                    ("Safety information", "Liver injury"),
                ],
                "/a.pdf",
            )
        ],
    )
    write(
        run / "texts.jsonl",
        [
            {
                "key": "A#1",
                "file": "f.pdf",
                "source_ref": "https://www.sfda.gov.sa/a.pdf",
                "pages": 3,
                "chars": 20,
                "text": "Dear Healthcare Professional",
                "ocr": True,
            }
        ],
    )

    [document] = StoredListDocuments(tmp_path, "lists-1").documents("dhpc")

    assert document.title == "Gilenya (fingolimod)"
    assert document.text.startswith("Product: Gilenya (fingolimod)")
    assert "Dear Healthcare Professional" in document.text
    assert document.source_ref == "https://www.sfda.gov.sa/a.pdf"
    assert document.ocr is True
    assert document.published == "2021-01-10"
    assert document.trust == "official"
    assert document.fetched_at == "2026-11-18T10:00:00+00:00"


def test_a_row_with_a_detail_page_lists_its_labelled_fields_and_skips_buttons(
    tmp_path: Path,
) -> None:
    run = tmp_path / "drugs-circulars" / "lists-1"
    write(
        run / "records.jsonl",
        [
            record(
                "R#1",
                [
                    ("Trade Name", "Dopram 100 MG /5ML"),
                    ("Date", "2025-11-02"),
                    ("Details", "Display"),
                ],
                "/en/x/1",
            )
        ],
    )
    write(
        run / "details.jsonl",
        [
            {
                "key": "R#1",
                "detail": [
                    {"label": "Title", "value": "Voluntary Recall of two batches"},
                    {"label": "سبب السحب", "value": "non-compliance"},
                    {"label": "Body", "value": "Download"},
                ],
            }
        ],
    )

    [document] = StoredListDocuments(tmp_path, "lists-1").documents("drugs-circulars")

    assert document.title == "Voluntary Recall of two batches"
    assert "سبب السحب: non-compliance" in document.text
    assert "Display" not in document.text
    assert "Download" not in document.text
    assert document.source_ref == "https://www.sfda.gov.sa/en/x/1"
    assert document.ocr is False


def test_a_list_row_without_detail_or_text_is_a_short_document(tmp_path: Path) -> None:
    run = tmp_path / "safety-labeling" / "lists-1"
    write(
        run / "records.jsonl",
        [
            record(
                "L#1",
                [
                    ("Scientific Name", "Topiramate"),
                    ("Trade Name", "Topamax"),
                    ("Updated Section", "4.2 Posology"),
                    ("Month", "Sep,2022"),
                ],
            )
        ],
    )

    [document] = StoredListDocuments(tmp_path, "lists-1").documents("safety-labeling")

    assert document.title == "Topamax"
    assert document.text.splitlines() == [
        "Scientific Name: Topiramate",
        "Trade Name: Topamax",
        "Updated Section: 4.2 Posology",
        "Month: Sep,2022",
    ]
    assert document.published == "Sep,2022"
    assert document.source_ref == "https://www.sfda.gov.sa/en/list?page=0"


def test_a_list_that_was_never_crawled_has_no_documents(tmp_path: Path) -> None:
    assert StoredListDocuments(tmp_path, "lists-1").documents("rmm") == []
