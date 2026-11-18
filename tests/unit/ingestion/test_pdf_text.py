"""Text of downloaded PDFs, on a tiny PDF built in the test."""

import json
import zipfile
from pathlib import Path

from pharmavique.ingestion.infrastructure.connectors.sfda_web.pdf_text import (
    extract_all,
    extract_pdf_text,
    ocr_empty_texts,
    ocr_image_texts,
)


def tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET"
    objects = [
        "<</Type/Catalog/Pages 2 0 R>>",
        "<</Type/Pages/Kids[3 0 R]/Count 1>>",
        "<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]/Contents 4 0 R"
        "/Resources<</Font<</F1 5 0 R>>>>>>",
        f"<</Length {len(stream)}>>\nstream\n{stream}\nendstream",
        "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    body = "%PDF-1.4\n"
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n{content}\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    body += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    body += f"trailer\n<</Root 1 0 R/Size {len(objects) + 1}>>\nstartxref\n{xref}\n%%EOF\n"
    return body.encode("latin-1")


def test_the_text_layer_of_a_pdf_is_read(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(tiny_pdf("Safety signal of Dabigatran"))
    text, pages = extract_pdf_text(path)
    assert "Safety signal of Dabigatran" in text
    assert pages == 1


def test_every_stored_pdf_is_read_once_and_other_files_are_left_alone(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(tiny_pdf("Hello alert"))
    (folder / "bad.pdf").write_bytes(b"not a pdf at all")
    (folder / "pic.jpg").write_bytes(b"\xff\xd8\xff")
    index = tmp_path / "files.jsonl"
    index.write_text(
        "\n".join(
            json.dumps({"key": key, "file": name, "source_ref": f"https://x/{name}"})
            for key, name in (("A#1", "a.pdf"), ("B#2", "bad.pdf"), ("C#3", "pic.jpg"))
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "texts.jsonl"
    first = extract_all(index, folder, out)
    assert first == {
        "stored_before": 0,
        "extracted": 1,
        "empty": 0,
        "unreadable": 1,
        "skipped": 1,
    }
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [row["key"] for row in rows] == ["A#1"]
    assert "Hello alert" in rows[0]["text"]
    assert rows[0]["source_ref"] == "https://x/a.pdf"

    again = extract_all(index, folder, out)
    assert again["extracted"] == 0
    assert again["stored_before"] == 1


def _texts(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def _read(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_scanned_pdf_gets_its_text_from_ocr_and_is_marked_as_ocr(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    out = tmp_path / "texts.jsonl"
    _texts(
        out,
        [
            {
                "key": "A#1",
                "file": "a.pdf",
                "source_ref": "u/a",
                "pages": 1,
                "chars": 5,
                "text": "Real",
            },
            {
                "key": "B#2",
                "file": "b.pdf",
                "source_ref": "u/b",
                "pages": 3,
                "chars": 0,
                "text": "",
            },
        ],
    )
    asked: list[str] = []

    def reader(path: Path) -> str | None:
        asked.append(path.name)
        return "Dear Healthcare Professional"

    counts = ocr_empty_texts(out, folder, reader)

    assert asked == ["b.pdf"]  # the PDF that already has text is not read again
    assert counts == {"candidates": 1, "read": 1, "still_empty": 0, "failed": 0}
    rows = {row["key"]: row for row in _read(out)}
    assert rows["A#1"]["text"] == "Real"
    assert "ocr" not in rows["A#1"]
    assert rows["B#2"]["text"] == "Dear Healthcare Professional"
    assert rows["B#2"]["ocr"] is True
    assert rows["B#2"]["chars"] == len("Dear Healthcare Professional")
    assert rows["B#2"]["source_ref"] == "u/b"


def test_ocr_that_fails_or_finds_nothing_keeps_the_record_as_it_was(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    out = tmp_path / "texts.jsonl"
    rows = [
        {"key": "B#2", "file": "b.pdf", "source_ref": "u/b", "pages": 1, "chars": 0, "text": ""},
        {"key": "C#3", "file": "c.pdf", "source_ref": "u/c", "pages": 1, "chars": 0, "text": ""},
    ]
    _texts(out, rows)

    def reader(path: Path) -> str | None:
        return None if path.name == "b.pdf" else "   "

    counts = ocr_empty_texts(out, folder, reader)

    assert counts == {"candidates": 2, "read": 0, "still_empty": 1, "failed": 1}
    assert _read(out) == rows


def test_repeating_the_ocr_does_not_read_the_same_pdf_again(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    out = tmp_path / "texts.jsonl"
    _texts(
        out,
        [{"key": "B#2", "file": "b.pdf", "source_ref": "u/b", "pages": 1, "chars": 0, "text": ""}],
    )
    calls: list[str] = []

    def reader(path: Path) -> str | None:
        calls.append(path.name)
        return "text"

    ocr_empty_texts(out, folder, reader)
    ocr_empty_texts(out, folder, reader)

    assert calls == ["b.pdf"]


def tiny_docx(*paragraphs: str) -> bytes:
    import io

    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _index(path: Path, rows: list[tuple[str, str]]) -> None:
    path.write_text(
        "".join(
            json.dumps({"key": key, "file": name, "source_ref": f"https://x/{name}"}) + "\n"
            for key, name in rows
        ),
        encoding="utf-8",
    )


def test_a_word_file_is_read_paragraph_by_paragraph(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    (folder / "a.docx").write_bytes(tiny_docx("Safety signal", "Recommendations"))
    index = tmp_path / "files.jsonl"
    _index(index, [("A#1", "a.docx")])
    out = tmp_path / "texts.jsonl"

    counts = extract_all(index, folder, out)

    assert counts["extracted"] == 1
    assert _read(out)[0]["text"] == "Safety signal\n\nRecommendations"
    assert "ocr" not in _read(out)[0]


def test_a_picture_gets_its_text_from_ocr_once_and_is_marked_as_ocr(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    index = tmp_path / "files.jsonl"
    _index(index, [("A#1", "a.pdf"), ("B#2", "b.jpg"), ("C#3", "c.png"), ("D#4", "d.jpg")])
    out = tmp_path / "texts.jsonl"
    _texts(
        out,
        [{"key": "A#1", "file": "a.pdf", "source_ref": "u", "pages": 1, "chars": 1, "text": "x"}],
    )
    asked: list[str] = []

    def reader(path: Path) -> str | None:
        asked.append(path.name)
        return None if path.name == "d.jpg" else f"text of {path.name}"

    counts = ocr_image_texts(index, folder, out, reader)

    assert asked == ["b.jpg", "c.png", "d.jpg"]  # the PDF is not a picture
    assert counts == {"candidates": 3, "read": 2, "still_empty": 0, "failed": 1}
    rows = {row["key"]: row for row in _read(out)}
    assert rows["B#2"]["text"] == "text of b.jpg"
    assert rows["B#2"]["ocr"] is True
    assert rows["B#2"]["source_ref"] == "https://x/b.jpg"
    assert "D#4" not in rows  # a failed picture is retried next time, not stored as empty

    asked.clear()
    ocr_image_texts(index, folder, out, reader)
    assert asked == ["d.jpg"]


def test_a_picture_with_no_readable_text_is_not_stored(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    index = tmp_path / "files.jsonl"
    _index(index, [("B#2", "b.jpg")])
    out = tmp_path / "texts.jsonl"

    counts = ocr_image_texts(index, folder, out, lambda path: "  ")

    assert counts == {"candidates": 1, "read": 0, "still_empty": 1, "failed": 0}
    assert not out.exists() or _read(out) == []
