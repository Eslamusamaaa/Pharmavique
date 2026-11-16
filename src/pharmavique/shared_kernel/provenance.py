"""Provenance carried by every stored record: where it came from and how far to trust it."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pharmavique.shared_kernel.errors import InvariantViolation


class TrustLevel(StrEnum):
    OFFICIAL = "official"
    UNOFFICIAL_UNVERIFIED = "unofficial_unverified"


@dataclass(frozen=True, slots=True)
class Provenance:
    source: str
    source_ref: str  # source URL or file
    fetched_at: datetime
    snapshot_id: str
    trust: TrustLevel

    def __post_init__(self) -> None:
        for name in ("source", "source_ref", "snapshot_id"):
            if not getattr(self, name).strip():
                raise InvariantViolation(f"provenance {name} must not be blank")
        if self.fetched_at.utcoffset() is None:
            raise InvariantViolation("provenance fetched_at must be timezone-aware")
