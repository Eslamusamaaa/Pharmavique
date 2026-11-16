"""Turn stored crawl records (JSON) into the flat `SourceRecord` the diff engine compares."""

from collections.abc import Iterable, Mapping
from typing import Any

from pharmavique.ingestion.domain.records import SourceRecord

_IGNORED_LIST_FIELDS = frozenset({"list_page"})  # position in the list, not a property of the drug


def to_source_record(record: Mapping[str, Any]) -> SourceRecord:
    """Flatten one record. Field names look like `list.price`, `en.Price`, `ar.السعر`.

    A label that repeats on one page gets `#2`, `#3`, ... so no value is silently overwritten.
    Provenance is deliberately left out: fetching the same data again is not a change.
    """
    fields: dict[str, str] = {}
    for name, value in record["list"].items():
        if name not in _IGNORED_LIST_FIELDS:
            fields[f"list.{name}"] = str(value)

    for language in ("en", "ar"):
        section = record.get(language)
        if not section:
            continue
        seen: dict[str, int] = {}
        for item in section:
            label = item["label"]
            seen[label] = seen.get(label, 0) + 1
            suffix = "" if seen[label] == 1 else f"#{seen[label]}"
            fields[f"{language}.{label}{suffix}"] = item["value"]
    return SourceRecord(record["key"], fields)


def to_source_records(records: Iterable[Mapping[str, Any]]) -> dict[str, SourceRecord]:
    return {r["key"]: to_source_record(r) for r in records}
