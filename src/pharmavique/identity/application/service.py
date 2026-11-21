"""Sign up, confirm the email with a code, sign in, keep a session, sign out, delete the account.

Signing up makes an unconfirmed account and emails a six-digit code; there is no session until the
code is entered. The code is random, kept only as a keyed hash, valid for ten minutes, allows five
wrong tries and is used once; sending is limited (one a minute, five an hour), and asking for a new
code never reveals whether an address has an account.

Access tokens are short-lived and stateless. Refresh tokens are random, stored only as a hash,
used once and replaced on every refresh; if a used token comes back (a replay), every session of
that user ends. This answers the token-revocation question (Q-13): a stolen refresh token lives
until its owner next refreshes, and an access token for at most `ACCESS_MINUTES`.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID, uuid4

from pharmavique.identity.application.messages import verification_email
from pharmavique.identity.application.ports import (
    AccessTokens,
    CodeRecord,
    CodeStore,
    PasswordHasher,
    RefreshRecord,
    SessionStore,
    UserRepository,
)
from pharmavique.identity.domain.user import (
    CODE_DIGITS,
    CODE_MAX_ATTEMPTS,
    CODE_MAX_PER_HOUR,
    CODE_RESEND_SECONDS,
    CODE_TTL_MINUTES,
    SELF_SERVICE_ROLES,
    TENANT_ROLES,
    CodeLocked,
    EmailNotVerified,
    EmailTaken,
    InvalidCode,
    InvalidCredentials,
    SessionRejected,
    User,
    check_password,
    normalize_email,
)
from pharmavique.shared_kernel.email import EmailMessage
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
    email_verified: bool = True
    email_notifications: bool = True


@dataclass(frozen=True, slots=True)
class Registration:
    """A new, unconfirmed account and the email to send it (there is no session yet)."""

    user: UserView
    email: EmailMessage


@dataclass(frozen=True, slots=True)
class Session:
    access_token: str
    refresh_token: str
    expires_in: int
    user: UserView


def _view(user: User) -> UserView:
    return UserView(
        user.id, user.email, user.role, user.tenant_id, user.verified, user.email_notifications
    )


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
        codes: CodeStore,
        code_key: bytes,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._hasher = hasher
        self._tokens = tokens
        self._clock = clock
        self._codes = codes
        self._code_key = code_key
        self._dummy_hash: str | None = None

    async def register(self, email: str, password: str, role: Role) -> Registration:
        if role not in SELF_SERVICE_ROLES:
            raise InvariantViolation("this role cannot be chosen at sign-up")
        user = await self._new_user(email, password, role)
        message = await self._issue_code(user)
        if message is None:  # a brand-new user has no earlier codes to count
            raise InvariantViolation("could not make a verification code")
        return Registration(_view(user), message)

    async def create_operator(self, email: str, password: str) -> UserView:
        """Made by a command on the server, never through the public sign-up. The person at the
        server's console is trusted, so the account starts confirmed."""
        user = await self._new_user(email, password, Role.OPERATOR, verified=True)
        return _view(user)

    async def verify_email(self, email: str, code: str) -> Session:
        """Confirm the address with the emailed code and open the first session."""
        try:
            user = await self._users.by_email(normalize_email(email))
        except InvariantViolation:
            raise InvalidCode from None
        if user is None:
            raise InvalidCode
        record = await self._codes.latest(user.id)
        if record is None or record.expires_at <= self._clock.now():
            raise InvalidCode
        if record.attempts >= CODE_MAX_ATTEMPTS:
            raise CodeLocked
        if not hmac.compare_digest(record.code_hash, self._hash_code(user.id, code.strip())):
            if await self._codes.add_attempt(record.id) >= CODE_MAX_ATTEMPTS:
                raise CodeLocked
            raise InvalidCode
        if not await self._codes.consume(record.id):
            raise InvalidCode
        now = self._clock.now()
        await self._users.mark_verified(user.id, now)
        return await self._open_session(replace(user, email_verified_at=now))

    async def resend_code(self, email: str) -> EmailMessage | None:
        """A new code for an unconfirmed account, or None. Never says which: an address with no
        account, an already confirmed one and a request that is too soon all look the same."""
        try:
            user = await self._users.by_email(normalize_email(email))
        except InvariantViolation:
            return None
        if user is None or user.verified:
            return None
        return await self._issue_code(user)

    async def set_email_notifications(self, user_id: UUID, enabled: bool) -> bool:
        return await self._users.set_email_notifications(user_id, enabled)

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
        if not user.verified:
            raise EmailNotVerified  # only after the password was right: no address is revealed
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

    def _hash_code(self, user_id: UUID, code: str) -> str:
        return hmac.new(self._code_key, f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()

    async def _issue_code(self, user: User) -> EmailMessage | None:
        now = self._clock.now()
        recent = await self._codes.latest(user.id)
        if recent is not None and (now - recent.created_at).total_seconds() < CODE_RESEND_SECONDS:
            return None
        if await self._codes.count_since(user.id, now - timedelta(hours=1)) >= CODE_MAX_PER_HOUR:
            return None
        code = "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))
        await self._codes.add(
            CodeRecord(
                id=uuid4(),
                user_id=user.id,
                code_hash=self._hash_code(user.id, code),
                expires_at=now + timedelta(minutes=CODE_TTL_MINUTES),
                created_at=now,
            )
        )
        return verification_email(user.email, code, CODE_TTL_MINUTES)

    async def _new_user(
        self, email: str, password: str, role: Role, verified: bool = False
    ) -> User:
        normalized = normalize_email(email)
        check_password(password, normalized)
        user = User(
            id=uuid4(),
            email=normalized,
            password_hash=await self._hasher.hash(password),
            role=role,
            tenant_id=uuid4() if role in TENANT_ROLES else None,
            created_at=self._clock.now(),
            email_verified_at=self._clock.now() if verified else None,
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
