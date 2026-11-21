"""What other contexts may use from `identity` (published language)."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pharmavique.shared_kernel.principal import Principal


class TokenVerifier(Protocol):
    """Turns a bearer token into the caller, without a call to the identity database."""

    def verify_token(self, token: str) -> Principal | None: ...


@dataclass(frozen=True, slots=True)
class Contact:
    email: str
    notify: bool  # the person allows notification emails


class UserDirectory(Protocol):
    async def contacts(self, user_ids: Iterable[UUID]) -> dict[UUID, Contact]:
        """Email addresses of these people, only for accounts whose address was confirmed."""
        ...


__all__ = ["Contact", "TokenVerifier", "UserDirectory"]
