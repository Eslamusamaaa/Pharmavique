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

    async def mark_verified(self, user_id: UUID, at: datetime) -> None: ...

    async def set_email_notifications(self, user_id: UUID, enabled: bool) -> bool: ...


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


@dataclass(frozen=True, slots=True)
class CodeRecord:
    id: UUID
    user_id: UUID
    code_hash: str  # a keyed hash: the code itself is never stored
    expires_at: datetime
    created_at: datetime
    attempts: int = 0


class CodeStore(Protocol):
    async def add(self, record: CodeRecord) -> None:
        """Store a new code and retire the user's earlier ones."""
        ...

    async def latest(self, user_id: UUID) -> CodeRecord | None:
        """The user's newest code that has not been used."""
        ...

    async def add_attempt(self, code_id: UUID) -> int:
        """Count one wrong try; the number of tries so far."""
        ...

    async def consume(self, code_id: UUID) -> bool:
        """Use the code once. False when it was already used."""
        ...

    async def count_since(self, user_id: UUID, since: datetime) -> int:
        """How many codes were sent to the user since then."""
        ...


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
