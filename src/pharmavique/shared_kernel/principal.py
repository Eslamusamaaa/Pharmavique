"""The authenticated caller, as other contexts see it (built from signed token claims)."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pharmavique.shared_kernel.errors import InvariantViolation

UserId = UUID
TenantId = UUID


class Role(StrEnum):
    PATIENT = "patient"
    PHARMACIST = "pharmacist"
    COMPANY = "company"


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UserId
    tenant_id: TenantId | None  # patients have no tenant; pharmacies and companies do
    roles: frozenset[Role]

    def __post_init__(self) -> None:
        if not self.roles:
            raise InvariantViolation("a principal needs at least one role")
