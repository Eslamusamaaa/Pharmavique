"""Read the pages a crawl has stored on disk as source records, even while the crawl still runs."""

import json
from collections.abc import Collection, Iterator
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

    def records(self, skip: Collection[str] = frozenset()) -> Iterator[dict[str, Any]]:
        """Every stored drug; keys in `skip` are passed over before their pages are read."""
        folder = self._store.run_dir / "details" / "en"
        for path in sorted(folder.glob(f"*{_SUFFIX}")):
            key = unquote(path.name.removesuffix(_SUFFIX))
            if key in skip:
                continue
            english = self._read(path)
            if english is None:
                continue
            page, fields = english
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


class JsonlRecords:
    """Implements the `RecordSource` port over a run's `records.jsonl` (the parsed crawl output).

    Used when the raw pages of a run are not on this machine; the records hold the same parsed
    fields `StoredRecords` builds from the pages, plus the list row and full provenance.
    """

    def __init__(self, store: SnapshotStore) -> None:
        self._store = store

    def records(self, skip: Collection[str] = frozenset()) -> Iterator[dict[str, Any]]:
        path = self._store.records_path
        if not path.exists():
            return
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record: dict[str, Any] = json.loads(line)
                if record.get("key") in skip or not record.get("en"):
                    continue
                yield record


# The parts of a record that say what the drug is; the provenance (fetch times) changes every run
# even when nothing about the drug did, so it is not compared.
_COMPARED = ("key", "list", "en", "ar")


def _fingerprint(record: dict[str, Any]) -> str:
    return json.dumps({k: record.get(k) for k in _COMPARED}, sort_keys=True, ensure_ascii=False)


class ChangedRecords:
    """The records of a run that differ from the run that was last loaded into the database.

    The daily refresh used to load every drug (9,213) although only a few dozen had changed, and
    each load reads the stored drug back from the database to compare: Neon bills every byte that
    leaves it (public network transfer). The comparison is made here, between two local files.
    When the earlier run's records are not on this machine, every record is loaded, as before.
    """

    def __init__(self, source: JsonlRecords, previous: SnapshotStore) -> None:
        self._source = source
        self._previous = previous

    def _known(self) -> dict[str, str]:
        path = self._previous.records_path
        if not path.exists():
            return {}
        known: dict[str, str] = {}
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    known[str(record.get("key"))] = _fingerprint(record)
        return known

    def records(self, skip: Collection[str] = frozenset()) -> Iterator[dict[str, Any]]:
        known = self._known()
        for record in self._source.records(skip):
            if known.get(str(record.get("key"))) != _fingerprint(record):
                yield record
