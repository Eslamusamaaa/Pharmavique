"""Text of downloaded PDFs, on a tiny PDF built in the test."""

import json
from pathlib import Path

from pharmavique.ingestion.infrastructure.connectors.sfda_web.pdf_text import (
    extract_all,
    extract_pdf_text,
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
