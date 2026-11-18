"""Read the text of the PDFs downloaded for a list (the safety alerts, the DHPC letters).

`extract_all` reads the text layer. A scanned page has none, so it comes back empty and is recorded
as such. `ocr_empty_texts` then reads those PDFs with an OCR reader handed in by the caller and
marks the record `ocr: true`, because OCR text can hold misread characters and must never be shown
as exact. The text is kept with the file it came from, so every sentence can be traced to its source
document.
"""

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pypdf import PdfReader

_log = logging.getLogger("sfda.list.texts")


def extract_pdf_text(path: Path) -> tuple[str, int]:
    """(text, page count) of a PDF; empty text when the file has no text layer."""
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join(page for page in pages if page), len(pages)


def extract_all(files_index: Path, folder: Path, out_path: Path) -> dict[str, int]:
    """Extract the text of every stored PDF listed in `files_index`; safe to repeat."""
    done = _stored_keys(out_path)
    counts = {"stored_before": len(done), "extracted": 0, "empty": 0, "unreadable": 0, "skipped": 0}
    rows = [
        json.loads(line)
        for line in files_index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with out_path.open("a", encoding="utf-8") as out:
        for row in rows:
            if row["key"] in done:
                continue
            if not row["file"].lower().endswith(".pdf"):
                counts["skipped"] += 1  # images and Word files are kept, not read
                continue
            try:
                text, pages = extract_pdf_text(folder / row["file"])
            except Exception as exc:  # a damaged file must not stop the others
                counts["unreadable"] += 1
                _log.warning("cannot read %s: %s", row["file"], exc)
                continue
            counts["extracted" if text else "empty"] += 1
            record: dict[str, Any] = {
                "key": row["key"],
                "file": row["file"],
                "source_ref": row["source_ref"],
                "pages": pages,
                "chars": len(text),
                "text": text,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    return counts


PdfOcr = Callable[[Path], str | None]  # text of a whole PDF, None when it could not be read


def ocr_empty_texts(texts_path: Path, folder: Path, read: PdfOcr) -> dict[str, int]:
    """Fill the records of `texts_path` that have no text by reading their PDF with `read`.

    Safe to repeat: a record that has text (from the text layer or an earlier OCR) is not read
    again. A PDF that fails or yields nothing keeps its record as it was.
    """
    records = [
        json.loads(line)
        for line in texts_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    counts = {"candidates": 0, "read": 0, "still_empty": 0, "failed": 0}
    for record in records:
        if record.get("text", "").strip() or not record["file"].lower().endswith(".pdf"):
            continue
        counts["candidates"] += 1
        try:
            text = read(folder / record["file"])
        except Exception as exc:  # one bad file must not stop the others
            _log.warning("cannot OCR %s: %s", record["file"], exc)
            text = None
        if text is None:
            counts["failed"] += 1
        elif not text.strip():
            counts["still_empty"] += 1
        else:
            record.update(text=text.strip(), chars=len(text.strip()), ocr=True)
            counts["read"] += 1
    staged = texts_path.with_suffix(texts_path.suffix + ".tmp")
    staged.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    os.replace(staged, texts_path)
    return counts


def _stored_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        json.loads(line)["key"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
