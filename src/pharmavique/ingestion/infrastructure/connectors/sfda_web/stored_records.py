"""Read the pages a crawl has stored on disk as source records, even while the crawl still runs."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import (
    ParseError,
    parse_details_page,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore

_SUFFIX = ".json.gz"


class StoredRecords:
    """Implements the `RecordSource` port over a crawl snapshot folder."""

    def __init__(self, store: SnapshotStore) -> None:
        self._store = store

    def records(self) -> Iterator[dict[str, Any]]:
        folder = self._store.run_dir / "details" / "en"
        for path in sorted(folder.glob(f"*{_SUFFIX}")):
            english = self._read(path)
            if english is None:
                continue
            page, fields = english
            key = unquote(path.name.removesuffix(_SUFFIX))
            arabic_path = self._store.details_path("ar", key)
            arabic = self._read(arabic_path) if self._store.has(arabic_path) else None
            yield {
                "key": key,
                "list": {},
                "en": fields,
                "ar": arabic[1] if arabic else None,
                "provenance": {
                    "en_fetched_at": page.fetched_at.isoformat(),
                    "en_source_ref": page.url,
                },
            }

    def _read(self, path: Path) -> tuple[FetchedPage, list[dict[str, str]]] | None:
        try:
            page = self._store.load_page(path)
            parsed = parse_details_page(page.html)
        except (ParseError, OSError, ValueError, KeyError):
            return None  # unreadable or half-written file: skip it, do not stop the load
        return page, [{"label": f.label, "value": f.value} for f in parsed.fields]
