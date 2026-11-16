"""Diff engine: what was added, removed or changed between two snapshots. Pure, no I/O."""

from collections.abc import Mapping

from pharmavique.ingestion.domain.records import (
    ChangeSet,
    FieldChange,
    RecordChange,
    SourceRecord,
)


def _field_changes(old: Mapping[str, str], new: Mapping[str, str]) -> tuple[FieldChange, ...]:
    return tuple(
        FieldChange(name, old.get(name), new.get(name))
        for name in sorted(old.keys() | new.keys())
        if old.get(name) != new.get(name)
    )


def diff(old: Mapping[str, SourceRecord], new: Mapping[str, SourceRecord]) -> ChangeSet:
    """Compare two snapshots keyed by record key. Output is sorted so reports are stable."""
    added = tuple(new[key] for key in sorted(new.keys() - old.keys()))
    removed = tuple(old[key] for key in sorted(old.keys() - new.keys()))
    changed = tuple(
        RecordChange(key, changes)
        for key in sorted(old.keys() & new.keys())
        if (changes := _field_changes(old[key].fields, new[key].fields))
    )
    return ChangeSet(added=added, removed=removed, changed=changed)
