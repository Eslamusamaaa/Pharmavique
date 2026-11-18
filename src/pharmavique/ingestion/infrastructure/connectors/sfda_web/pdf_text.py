"""Read the text of the PDFs downloaded for a list (the safety alerts).

Only text PDFs are read: a scanned page has no text layer, so it comes back empty and is recorded
as such (no OCR here). The text is kept with the file it came from, so every sentence can be
traced to its source document.
"""

import json
import logging
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


def _stored_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        json.loads(line)["key"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
