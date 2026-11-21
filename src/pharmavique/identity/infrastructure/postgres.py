"""PostgreSQL stores over the `identity` schema."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.identity.application.ports import RefreshRecord
from pharmavique.identity.domain.user import User
from pharmavique.shared_kernel.principal import Role

_INSERT = text(
    "INSERT INTO identity.users (id, email, password_hash, role, tenant_id, created_at) "
    "VALUES (:id, :email, :password_hash, :role, :tenant_id, :created_at)"
)
_BY_EMAIL = text(
    "SELECT id, email, password_hash, role, tenant_id, created_at "
    "FROM identity.users WHERE email = :email"
)
_BY_ID = text(
    "SELECT id, email, password_hash, role, tenant_id, created_at "
    "FROM identity.users WHERE id = :id"
)


def _user(row: object) -> User:
    r = row._mapping  # type: ignore[attr-defined]
    return User(
        id=r["id"],
        email=r["email"],
        password_hash=r["password_hash"],
        role=Role(r["role"]),
        tenant_id=r["tenant_id"],
        created_at=r["created_at"],
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
