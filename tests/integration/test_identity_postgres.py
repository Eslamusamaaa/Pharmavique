"""The identity tables against a real Postgres: unique emails, one-time refresh tokens, cascade."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.identity.application.ports import RefreshRecord
from pharmavique.identity.domain.user import User
from pharmavique.identity.infrastructure.postgres import (
    PostgresSessionStore,
    PostgresUserRepository,
)
from pharmavique.shared_kernel.principal import Role

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def user(email: str = "ana@example.com", role: Role = Role.PATIENT) -> User:
    tenant = uuid4() if role in (Role.PHARMACIST, Role.COMPANY) else None
    return User(uuid4(), email, "scrypt$hash", role, tenant, NOW)


@pytest.fixture(autouse=True)
async def clean(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(text("TRUNCATE identity.refresh_tokens, identity.users CASCADE"))


async def test_a_user_round_trips_and_the_email_is_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users = PostgresUserRepository(session_factory)
    first = user(role=Role.PHARMACIST)

    assert await users.add(first) is True
    assert await users.add(user()) is False  # same email

    assert await users.by_email("ana@example.com") == first
    assert await users.by_id(first.id) == first
    assert await users.by_email("nobody@example.com") is None


async def test_a_refresh_token_can_be_used_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users, sessions = PostgresUserRepository(session_factory), PostgresSessionStore(session_factory)
    account = user()
    await users.add(account)
    record = RefreshRecord("h" * 64, account.id, NOW + timedelta(days=30))
    await sessions.save(record)

    assert await sessions.find(record.token_hash) == record
    assert await sessions.mark_used(record.token_hash) is True
    assert await sessions.mark_used(record.token_hash) is False  # a replay


async def test_revoking_a_user_removes_every_refresh_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users, sessions = PostgresUserRepository(session_factory), PostgresSessionStore(session_factory)
    account = user()
    await users.add(account)
    for name in ("a", "b"):
        await sessions.save(RefreshRecord(name * 64, account.id, NOW + timedelta(days=1)))

    await sessions.revoke_user(account.id)

    assert await sessions.find("a" * 64) is None
    assert await sessions.find("b" * 64) is None


async def test_deleting_a_user_removes_their_tokens_too(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users, sessions = PostgresUserRepository(session_factory), PostgresSessionStore(session_factory)
    account = user()
    await users.add(account)
    await sessions.save(RefreshRecord("c" * 64, account.id, NOW + timedelta(days=1)))

    await users.delete(account.id)

    assert await users.by_id(account.id) is None
    assert await sessions.find("c" * 64) is None


async def test_the_database_refuses_a_tenant_on_a_patient_and_none_on_a_company(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users = PostgresUserRepository(session_factory)
    patient_with_tenant = User(uuid4(), "a@example.com", "h", Role.PATIENT, uuid4(), NOW)
    company_without = User(uuid4(), "b@example.com", "h", Role.COMPANY, None, NOW)

    # a violated CHECK is not an email clash, but any integrity error is reported as False
    assert await users.add(patient_with_tenant) is False
    assert await users.add(company_without) is False


async def test_the_identity_migration_is_reversible(
    migrated_url: URL, make_alembic_config: object
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    await asyncio.to_thread(command.downgrade, config, "identity@base")
    await asyncio.to_thread(command.upgrade, config, "identity@head")
