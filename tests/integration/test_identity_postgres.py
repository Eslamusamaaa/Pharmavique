"""The identity tables against a real Postgres: unique emails, one-time refresh tokens, cascade."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.identity.application.ports import CodeRecord, RefreshRecord
from pharmavique.identity.domain.user import User
from pharmavique.identity.infrastructure.postgres import (
    PostgresCodeStore,
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
        await session.execute(
            text("TRUNCATE identity.email_codes, identity.refresh_tokens, identity.users CASCADE")
        )


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


async def test_confirming_the_email_and_the_notification_switch_are_kept(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users = PostgresUserRepository(session_factory)
    account = user()
    await users.add(account)
    assert (await users.by_id(account.id)).email_verified_at is None  # type: ignore[union-attr]

    await users.mark_verified(account.id, NOW)
    await users.mark_verified(account.id, NOW + timedelta(days=1))  # a second time changes nothing
    assert await users.set_email_notifications(account.id, False) is True
    assert await users.set_email_notifications(uuid4(), False) is False

    stored = await users.by_id(account.id)
    assert stored is not None
    assert stored.email_verified_at == NOW
    assert stored.email_notifications is False


async def test_a_code_is_found_counted_used_once_and_replaced_by_a_newer_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users, codes = PostgresUserRepository(session_factory), PostgresCodeStore(session_factory)
    account = user()
    await users.add(account)
    first = CodeRecord(uuid4(), account.id, "a" * 64, NOW + timedelta(minutes=10), NOW)

    await codes.add(first)
    assert await codes.latest(account.id) == first
    assert await codes.add_attempt(first.id) == 1
    assert await codes.add_attempt(first.id) == 2
    assert (await codes.latest(account.id)).attempts == 2  # type: ignore[union-attr]

    second = CodeRecord(
        uuid4(), account.id, "b" * 64, NOW + timedelta(minutes=11), NOW + timedelta(minutes=1)
    )
    await codes.add(second)
    assert await codes.latest(account.id) == second  # the older code was retired
    assert await codes.consume(second.id) is True
    assert await codes.consume(second.id) is False  # used once
    assert await codes.latest(account.id) is None
    assert await codes.count_since(account.id, NOW) == 2
    assert await codes.count_since(account.id, NOW + timedelta(minutes=2)) == 0


async def test_codes_go_with_their_user(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users, codes = PostgresUserRepository(session_factory), PostgresCodeStore(session_factory)
    account = user()
    await users.add(account)
    await codes.add(CodeRecord(uuid4(), account.id, "c" * 64, NOW + timedelta(minutes=10), NOW))

    await users.delete(account.id)

    assert await codes.latest(account.id) is None
    assert await codes.count_since(account.id, NOW - timedelta(days=1)) == 0


async def test_the_identity_migration_is_reversible(
    migrated_url: URL, make_alembic_config: object
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    await asyncio.to_thread(command.downgrade, config, "identity@base")
    await asyncio.to_thread(command.upgrade, config, "identity@head")
