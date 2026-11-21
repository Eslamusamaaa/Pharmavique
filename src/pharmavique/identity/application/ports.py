"""What the identity use cases need from the outside world."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pharmavique.identity.domain.user import User
from pharmavique.shared_kernel.principal import Principal


class UserRepository(Protocol):
    async def add(self, user: User) -> bool:
        """Store the user. False when the email is already taken."""
        ...

    async def by_email(self, email: str) -> User | None: ...

    async def by_id(self, user_id: UUID) -> User | None: ...

    async def delete(self, user_id: UUID) -> None:
        """Delete the user and every session of theirs."""
        ...


@dataclass(frozen=True, slots=True)
class RefreshRecord:
    token_hash: str  # a hash: the token itself is never stored
    user_id: UUID
    expires_at: datetime


class SessionStore(Protocol):
    async def save(self, record: RefreshRecord) -> None: ...

    async def find(self, token_hash: str) -> RefreshRecord | None: ...

    async def mark_used(self, token_hash: str) -> bool:
        """Mark the token used. False when it was already used (a replay)."""
        ...

    async def revoke_user(self, user_id: UUID) -> None:
        """End every session of the user."""
        ...

    async def revoke(self, token_hash: str) -> None: ...


class PasswordHasher(Protocol):
    async def hash(self, password: str) -> str: ...

    async def verify(self, password: str, stored: str) -> bool: ...


class AccessTokens(Protocol):
    def issue(self, principal: Principal, now: datetime) -> tuple[str, int]:
        """A signed access token and how many seconds it lasts."""
        ...

    def verify(self, token: str, now: datetime) -> Principal | None:
        """The caller the token names, or None when it is invalid or expired."""
        ...
