"""Event base types. Integration events are the versioned, published subset of events."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from pharmavique.shared_kernel.errors import InvariantViolation


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    occurred_at: datetime
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.occurred_at.utcoffset() is None:
            raise InvariantViolation("event occurred_at must be timezone-aware")


@dataclass(frozen=True, kw_only=True)
class IntegrationEvent(DomainEvent):
    schema_version: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.schema_version < 1:
            raise InvariantViolation("event schema_version must be at least 1")
