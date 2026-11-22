"""Which rows of a daily list run still need their documents fetched and cut into chunks.

A daily run holds only the list rows. The full documents (detail pages, files, PDF and OCR text) are
fetched for the rows nobody has seen yet, so a day's work stays small and the chunks already stored
are never touched. Pure function, no I/O and no framework.
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any


def new_rows(rows: Sequence[Mapping[str, Any]], known: Collection[str]) -> list[Mapping[str, Any]]:
    """The rows whose `key` is not in `known`, in the run's order, each key once."""
    seen = set(known)
    fresh: list[Mapping[str, Any]] = []
    for row in rows:
        key = str(row["key"])
        if key in seen:
            continue
        seen.add(key)
        fresh.append(row)
    return fresh
