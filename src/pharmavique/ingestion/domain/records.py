"""Source records and the change set between two snapshots."""

from collections.abc import Mapping
from dataclasses import dataclass

from pharmavique.shared_kernel.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One drug as the source published it: a stable key plus flat name-to-text fields."""

    key: str
    fields: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise InvariantViolation("source record key must not be blank")


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    old: str | None  # None means the field did not exist before
    new: str | None  # None means the field no longer exists


@dataclass(frozen=True, slots=True)
class RecordChange:
    key: str
    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True)
class ChangeSet:
    added: tuple[SourceRecord, ...]
    removed: tuple[SourceRecord, ...]
    changed: tuple[RecordChange, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def counts(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "changed": len(self.changed),
        }
