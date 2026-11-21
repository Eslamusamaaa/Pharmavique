"""Sign up, sign in, keep a session, sign out and delete the account.

Access tokens are short-lived and stateless. Refresh tokens are random, stored only as a hash,
used once and replaced on every refresh; if a used token comes back (a replay), every session of
that user ends. This answers the token-revocation question (Q-13): a stolen refresh token lives
until its owner next refreshes, and an access token for at most `ACCESS_MINUTES`.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from pharmavique.identity.application.ports import (
    AccessTokens,
    PasswordHasher,
    RefreshRecord,
    SessionStore,
    UserRepository,
)
from pharmavique.identity.domain.user import (
    SELF_SERVICE_ROLES,
    TENANT_ROLES,
    EmailTaken,
    InvalidCredentials,
    SessionRejected,
    User,
    check_password,
    normalize_email,
)
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.ports import Clock
from pharmavique.shared_kernel.principal import Principal, Role

REFRESH_DAYS = 30
# A real hash of a throwaway password: checked when the email is unknown, so a wrong email and a
# wrong password take the same time and cannot be told apart from outside.
_DUMMY_PASSWORD = "not-a-real-account-password"  # noqa: S105


@dataclass(frozen=True, slots=True)
class UserView:
    id: UUID
    email: str
    role: Role
    tenant_id: UUID | None


@dataclass(frozen=True, slots=True)
class Session:
    access_token: str
    refresh_token: str
    expires_in: int
    user: UserView


def _view(user: User) -> UserView:
    return UserView(user.id, user.email, user.role, user.tenant_id)


def _principal(user: User) -> Principal:
    return Principal(user.id, user.tenant_id, frozenset({user.role}))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class IdentityService:
    def __init__(
        self,
        users: UserRepository,
        sessions: SessionStore,
        hasher: PasswordHasher,
        tokens: AccessTokens,
        clock: Clock,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._hasher = hasher
        self._tokens = tokens
        self._clock = clock
        self._dummy_hash: str | None = None

    async def register(self, email: str, password: str, role: Role) -> Session:
        if role not in SELF_SERVICE_ROLES:
            raise InvariantViolation("this role cannot be chosen at sign-up")
        user = await self._new_user(email, password, role)
        return await self._open_session(user)

    async def create_operator(self, email: str, password: str) -> UserView:
        """Made by a command on the server, never through the public sign-up."""
        user = await self._new_user(email, password, Role.OPERATOR)
        return _view(user)

    async def login(self, email: str, password: str) -> Session:
        try:
            normalized = normalize_email(email)
        except InvariantViolation:
            raise InvalidCredentials from None
        user = await self._users.by_email(normalized)
        if user is None:
            if self._dummy_hash is None:
                self._dummy_hash = await self._hasher.hash(_DUMMY_PASSWORD)
            await self._hasher.verify(password, self._dummy_hash)
            raise InvalidCredentials
        if not await self._hasher.verify(password, user.password_hash):
            raise InvalidCredentials
        return await self._open_session(user)

    async def refresh(self, refresh_token: str) -> Session:
        token_hash = _hash_token(refresh_token)
        record = await self._sessions.find(token_hash)
        if record is None:
            raise SessionRejected
        if not await self._sessions.mark_used(token_hash):
            await self._sessions.revoke_user(record.user_id)  # a replay: end every session
            raise SessionRejected
        if record.expires_at <= self._clock.now():
            raise SessionRejected
        user = await self._users.by_id(record.user_id)
        if user is None:
            raise SessionRejected
        return await self._open_session(user)

    async def logout(self, refresh_token: str) -> None:
        await self._sessions.revoke(_hash_token(refresh_token))

    async def delete_account(self, user_id: UUID) -> None:
        await self._users.delete(user_id)

    async def profile(self, user_id: UUID) -> UserView | None:
        user = await self._users.by_id(user_id)
        return _view(user) if user else None

    async def _new_user(self, email: str, password: str, role: Role) -> User:
        normalized = normalize_email(email)
        check_password(password, normalized)
        user = User(
            id=uuid4(),
            email=normalized,
            password_hash=await self._hasher.hash(password),
            role=role,
            tenant_id=uuid4() if role in TENANT_ROLES else None,
            created_at=self._clock.now(),
        )
        if not await self._users.add(user):
            raise EmailTaken
        return user

    async def _open_session(self, user: User) -> Session:
        now = self._clock.now()
        access, expires_in = self._tokens.issue(_principal(user), now)
        refresh = secrets.token_urlsafe(32)
        await self._sessions.save(
            RefreshRecord(_hash_token(refresh), user.id, now + timedelta(days=REFRESH_DAYS))
        )
        return Session(access, refresh, expires_in, _view(user))
