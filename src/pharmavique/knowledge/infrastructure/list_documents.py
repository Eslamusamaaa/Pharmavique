"""Read the official documents of a stored SFDA list run (`data/lists/<list>/<run>/`).

A document is one list row: its labelled cells, the labelled fields of its detail page
(`details.jsonl`) and the text of its downloaded file (`texts.jsonl`, marked when read by OCR).
Buttons such as "Display" and "Download" are not content and are left out. Nothing is invented: a
row with no detail and no file is a short document made of its own cells.
"""

import json
from pathlib import Path
from typing import Any

from pharmavique.knowledge.domain.chunks import SourceDocument

SITE = "https://www.sfda.gov.sa"
_TITLE_LABELS = ("Title", "Product", "Trade Name", "Brand name")
_DATE_LABELS = ("Date", "Month", "Approval Date", "التاريخ")
_NOT_CONTENT = frozenset({"display", "download", "عرض", "تحميل"})
_SKIPPED_LABELS = frozenset({"#", "attachment"})


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _keep(label: str, value: str) -> bool:
    return (
        bool(value.strip())
        and value.strip().lower() not in _NOT_CONTENT
        and label.strip().lower() not in _SKIPPED_LABELS
    )


def _first(pairs: list[tuple[str, str]], labels: tuple[str, ...]) -> str | None:
    for wanted in labels:
        for label, value in pairs:
            if label == wanted and value.strip():
                return value.strip()
    return None


class StoredListDocuments:
    def __init__(self, root: Path, run_id: str) -> None:
        self._root = Path(root)
        self._run_id = run_id

    def documents(self, list_name: str) -> list[SourceDocument]:
        run = self._root / list_name / self._run_id
        details = {row["key"]: row["detail"] for row in _jsonl(run / "details.jsonl")}
        texts = {row["key"]: row for row in _jsonl(run / "texts.jsonl")}
        found: list[SourceDocument] = []
        for record in _jsonl(run / "records.jsonl"):
            cells = [(c["label"], c["value"]) for c in record["list"]]
            detail = [(d["label"], d["value"]) for d in details.get(record["key"], [])]
            lines: list[str] = []
            for label, value in cells + detail:
                line = f"{label}: {value.strip()}"
                if _keep(label, value) and line not in lines:
                    lines.append(line)
            text_record = texts.get(record["key"])
            body = "\n".join(lines)
            if text_record and text_record.get("text", "").strip():
                body = f"{body}\n\n{text_record['text']}" if body else text_record["text"]
            provenance = record["provenance"]
            found.append(
                SourceDocument(
                    list_name=list_name,
                    row_key=record["key"],
                    title=_first(detail, _TITLE_LABELS) or _first(cells, _TITLE_LABELS) or "",
                    text=body,
                    source_ref=self._source_ref(record, text_record),
                    snapshot_id=provenance["snapshot_id"],
                    fetched_at=provenance.get("fetched_at"),
                    trust=provenance["trust"],
                    ocr=bool(text_record and text_record.get("ocr")),
                    published=_first(cells, _DATE_LABELS) or _first(detail, _DATE_LABELS),
                )
            )
        return found

    @staticmethod
    def _source_ref(record: dict[str, Any], text_record: dict[str, Any] | None) -> str:
        if text_record and text_record.get("source_ref"):
            return str(text_record["source_ref"])
        link = record.get("link")
        if link:
            return link if link.startswith("http") else f"{SITE}{link}"
        return str(record["provenance"]["source_ref"])
