"""PostgreSQL stores over the `identity` schema."""

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.identity.application.ports import CodeRecord, RefreshRecord
from pharmavique.identity.contracts import Contact
from pharmavique.identity.domain.user import RoleReview, User
from pharmavique.shared_kernel.principal import Role

_INSERT = text(
    "INSERT INTO identity.users (id, email, password_hash, role, tenant_id, created_at, "
    "email_verified_at, role_review) "
    "VALUES (:id, :email, :password_hash, :role, :tenant_id, :created_at, :verified_at, "
    ":role_review)"
)
_COLUMNS = (
    "id, email, password_hash, role, tenant_id, created_at, email_verified_at, "
    "email_notifications, role_review, role_reviewed_at, role_review_note"
)
_PENDING = text(
    f"SELECT {_COLUMNS} FROM identity.users "  # noqa: S608
    "WHERE role_review = 'pending' ORDER BY created_at, id LIMIT :limit"
)
_BY_EMAIL = text(f"SELECT {_COLUMNS} FROM identity.users WHERE email = :email")  # noqa: S608
_BY_ID = text(f"SELECT {_COLUMNS} FROM identity.users WHERE id = :id")  # noqa: S608


def _user(row: object) -> User:
    r = row._mapping  # type: ignore[attr-defined]
    return User(
        id=r["id"],
        email=r["email"],
        password_hash=r["password_hash"],
        role=Role(r["role"]),
        tenant_id=r["tenant_id"],
        created_at=r["created_at"],
        email_verified_at=r["email_verified_at"],
        email_notifications=r["email_notifications"],
        role_review=RoleReview(r["role_review"]),
        role_reviewed_at=r["role_reviewed_at"],
        role_review_note=r["role_review_note"],
    )


class PostgresUserRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, user: User) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    _INSERT,
                    {
                        "id": user.id,
                        "email": user.email,
                        "password_hash": user.password_hash,
                        "role": user.role.value,
                        "tenant_id": user.tenant_id,
                        "created_at": user.created_at,
                        "verified_at": user.email_verified_at,
                        "role_review": user.role_review.value,
                    },
                )
        except IntegrityError:
            return False  # the email is unique (the only constraint a caller can break)
        return True

    async def by_email(self, email: str) -> User | None:
        async with self._session_factory() as session:
            row = (await session.execute(_BY_EMAIL, {"email": email})).first()
        return _user(row) if row else None

    async def by_id(self, user_id: UUID) -> User | None:
        async with self._session_factory() as session:
            row = (await session.execute(_BY_ID, {"id": user_id})).first()
        return _user(row) if row else None

    async def delete(self, user_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM identity.users WHERE id = :id"), {"id": user_id}
            )  # refresh tokens go with it (ON DELETE CASCADE)

    async def mark_verified(self, user_id: UUID, at: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE identity.users SET email_verified_at = :at "
                    "WHERE id = :id AND email_verified_at IS NULL"
                ),
                {"id": user_id, "at": at},
            )

    async def set_email_notifications(self, user_id: UUID, enabled: bool) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE identity.users SET email_notifications = :e WHERE id = :id RETURNING id"
                ),
                {"id": user_id, "e": enabled},
            )
            return result.first() is not None

    async def set_role_review(
        self, user_id: UUID, review: RoleReview, at: datetime, note: str | None
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE identity.users SET role_review = :review, role_reviewed_at = :at, "
                    "role_review_note = :note WHERE id = :id"
                ),
                {"id": user_id, "review": review.value, "at": at, "note": note},
            )

    async def pending_role_reviews(self, limit: int) -> list[User]:
        async with self._session_factory() as session:
            rows = (await session.execute(_PENDING, {"limit": limit})).all()
        return [_user(row) for row in rows]


class PostgresUserDirectory:
    """Implements the published `UserDirectory`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def contacts(self, user_ids: Iterable[UUID]) -> dict[UUID, Contact]:
        ids = list(user_ids)
        if not ids:
            return {}
        async with self._session_factory() as session:
            rows = await session.execute(
                text(
                    "SELECT id, email, email_notifications FROM identity.users "
                    "WHERE id = ANY(:ids) AND email_verified_at IS NOT NULL"
                ),
                {"ids": ids},
            )
            return {r.id: Contact(r.email, r.email_notifications) for r in rows}


class PostgresCodeStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def add(self, record: CodeRecord) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE identity.email_codes SET consumed_at = :now "
                    "WHERE user_id = :u AND consumed_at IS NULL"
                ),
                {"u": record.user_id, "now": record.created_at},
            )
            await session.execute(
                text(
                    "INSERT INTO identity.email_codes "
                    "(id, user_id, code_hash, expires_at, created_at) "
                    "VALUES (:id, :u, :h, :e, :c)"
                ),
                {
                    "id": record.id,
                    "u": record.user_id,
                    "h": record.code_hash,
                    "e": record.expires_at,
                    "c": record.created_at,
                },
            )

    async def latest(self, user_id: UUID) -> CodeRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id, user_id, code_hash, expires_at, created_at, attempts "
                        "FROM identity.email_codes "
                        "WHERE user_id = :u AND consumed_at IS NULL "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"u": user_id},
                )
            ).first()
        if row is None:
            return None
        return CodeRecord(
            row.id, row.user_id, row.code_hash, row.expires_at, row.created_at, row.attempts
        )

    async def add_attempt(self, code_id: UUID) -> int:
        async with self._session_factory() as session, session.begin():
            value = await session.scalar(
                text(
                    "UPDATE identity.email_codes SET attempts = attempts + 1 "
                    "WHERE id = :id RETURNING attempts"
                ),
                {"id": code_id},
            )
        return int(value or 0)

    async def consume(self, code_id: UUID) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE identity.email_codes SET consumed_at = now() "
                    "WHERE id = :id AND consumed_at IS NULL RETURNING id"
                ),
                {"id": code_id},
            )
            return result.first() is not None

    async def count_since(self, user_id: UUID, since: datetime) -> int:
        async with self._session_factory() as session:
            value = await session.scalar(
                text(
                    "SELECT count(*) FROM identity.email_codes "
                    "WHERE user_id = :u AND created_at >= :since"
                ),
                {"u": user_id, "since": since},
            )
        return int(value or 0)


class PostgresSessionStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, record: RefreshRecord) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO identity.refresh_tokens (token_hash, user_id, expires_at) "
                    "VALUES (:h, :u, :e)"
                ),
                {"h": record.token_hash, "u": record.user_id, "e": record.expires_at},
            )

    async def find(self, token_hash: str) -> RefreshRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT token_hash, user_id, expires_at "
                        "FROM identity.refresh_tokens WHERE token_hash = :h"
                    ),
                    {"h": token_hash},
                )
            ).first()
        if row is None:
            return None
        return RefreshRecord(row.token_hash, row.user_id, row.expires_at)

    async def mark_used(self, token_hash: str) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE identity.refresh_tokens SET used = true "
                    "WHERE token_hash = :h AND used = false RETURNING token_hash"
                ),
                {"h": token_hash},
            )
            return result.first() is not None

    async def revoke_user(self, user_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM identity.refresh_tokens WHERE user_id = :u"), {"u": user_id}
            )

    async def revoke(self, token_hash: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM identity.refresh_tokens WHERE token_hash = :h"),
                {"h": token_hash},
            )
