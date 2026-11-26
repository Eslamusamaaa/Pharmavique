"""The identity tables against a real Postgres: unique emails, one-time refresh tokens, cascade."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.identity.application.ports import CodeRecord, RefreshRecord
from pharmavique.identity.domain.user import CodePurpose, RoleReview, User, initial_role_review
from pharmavique.identity.infrastructure.postgres import (
    PostgresCodeStore,
    PostgresSessionStore,
    PostgresUserDirectory,
    PostgresUserRepository,
)
from pharmavique.shared_kernel.principal import Role

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def user(email: str = "ana@example.com", role: Role = Role.PATIENT) -> User:
    tenant = uuid4() if role in (Role.PHARMACIST, Role.COMPANY) else None
    return User(
        uuid4(), email, "scrypt$hash", role, tenant, NOW, role_review=initial_role_review(role)
    )


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


async def test_a_reset_code_and_a_sign_up_code_live_side_by_side(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users, codes = PostgresUserRepository(session_factory), PostgresCodeStore(session_factory)
    account = user()
    await users.add(account)
    verify = CodeRecord(uuid4(), account.id, "a" * 64, NOW + timedelta(minutes=10), NOW)
    reset = CodeRecord(
        uuid4(),
        account.id,
        "b" * 64,
        NOW + timedelta(minutes=11),
        NOW + timedelta(minutes=1),
        purpose=CodePurpose.RESET,
    )

    await codes.add(verify)
    await codes.add(reset)

    assert await codes.latest(account.id) == verify  # the reset did not retire the sign-up code
    assert await codes.latest(account.id, CodePurpose.RESET) == reset
    newer = replace(reset, id=uuid4(), code_hash="c" * 64, created_at=NOW + timedelta(minutes=2))
    await codes.add(newer)
    assert await codes.latest(account.id, CodePurpose.RESET) == newer  # replaces only its own kind
    assert await codes.latest(account.id) == verify
    assert await codes.count_since(account.id, NOW) == 3  # the hourly cap counts every kind


async def test_choosing_a_new_password_changes_only_the_hash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users = PostgresUserRepository(session_factory)
    account = user()
    await users.add(account)
    other = user("bob@example.com")
    await users.add(other)

    new_hash = "scrypt$new"
    await users.set_password(account.id, new_hash)

    stored, untouched = await users.by_id(account.id), await users.by_id(other.id)
    assert stored is not None
    assert untouched is not None
    assert stored.password_hash == new_hash
    assert stored.email == account.email
    assert untouched.password_hash == other.password_hash


async def test_codes_sent_before_the_purpose_column_become_sign_up_codes(
    migrated_url: URL,
    make_alembic_config: object,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    users = PostgresUserRepository(session_factory)
    account = user()
    await users.add(account)
    await asyncio.to_thread(command.downgrade, config, "identity_0003")
    async with session_factory() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO identity.email_codes (id, user_id, code_hash, expires_at, created_at) "
                "VALUES (:id, :u, :h, :e, :c)"
            ),
            {
                "id": uuid4(),
                "u": account.id,
                "h": "d" * 64,
                "e": NOW + timedelta(minutes=10),
                "c": NOW,
            },
        )
    await asyncio.to_thread(command.upgrade, config, "identity@head")

    found = await PostgresCodeStore(session_factory).latest(account.id)

    assert found is not None
    assert found.code_hash == "d" * 64
    assert found.purpose is CodePurpose.VERIFY


async def test_going_back_drops_the_reset_codes_and_keeps_the_sign_up_ones(
    migrated_url: URL,
    make_alembic_config: object,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    users, codes = PostgresUserRepository(session_factory), PostgresCodeStore(session_factory)
    account = user()
    await users.add(account)
    await codes.add(CodeRecord(uuid4(), account.id, "a" * 64, NOW + timedelta(minutes=10), NOW))
    await codes.add(
        CodeRecord(
            uuid4(),
            account.id,
            "b" * 64,
            NOW + timedelta(minutes=10),
            NOW,
            purpose=CodePurpose.RESET,
        )
    )

    await asyncio.to_thread(command.downgrade, config, "identity_0003")
    async with session_factory() as session:
        left = (await session.execute(text("SELECT code_hash FROM identity.email_codes"))).all()

    assert [row.code_hash for row in left] == ["a" * 64]
    await asyncio.to_thread(command.upgrade, config, "identity@head")


async def test_the_directory_gives_addresses_only_for_confirmed_accounts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users, directory = (
        PostgresUserRepository(session_factory),
        PostgresUserDirectory(session_factory),
    )
    confirmed, unconfirmed, quiet = (
        user("a@example.com"),
        user("b@example.com"),
        user("c@example.com"),
    )
    for account in (confirmed, unconfirmed, quiet):
        await users.add(account)
    await users.mark_verified(confirmed.id, NOW)
    await users.mark_verified(quiet.id, NOW)
    await users.set_email_notifications(quiet.id, False)

    found = await directory.contacts([confirmed.id, unconfirmed.id, quiet.id, uuid4()])

    assert set(found) == {confirmed.id, quiet.id}  # an unconfirmed address is never offered
    assert (found[confirmed.id].email, found[confirmed.id].notify) == ("a@example.com", True)
    assert found[quiet.id].notify is False
    assert await directory.contacts([]) == {}


async def test_a_role_review_is_stored_and_the_waiting_list_is_oldest_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users = PostgresUserRepository(session_factory)
    older = user("a@example.com", Role.PHARMACIST)
    newer = replace(user("b@example.com", Role.COMPANY), created_at=NOW + timedelta(minutes=1))
    patient = user("c@example.com")
    for account in (newer, older, patient):
        await users.add(account)

    assert [u.email for u in await users.pending_role_reviews(10)] == [
        "a@example.com",
        "b@example.com",
    ]
    assert [u.email for u in await users.pending_role_reviews(1)] == ["a@example.com"]

    await users.set_role_review(older.id, RoleReview.REJECTED, NOW, "no licence found")

    stored = await users.by_id(older.id)
    assert stored is not None
    assert (stored.role_review, stored.role_reviewed_at, stored.role_review_note) == (
        RoleReview.REJECTED,
        NOW,
        "no licence found",
    )
    assert [u.email for u in await users.pending_role_reviews(10)] == ["b@example.com"]


async def test_a_patient_cannot_be_stored_as_waiting_for_review(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users = PostgresUserRepository(session_factory)
    account = user()
    await users.add(account)

    with pytest.raises(IntegrityError):
        await users.set_role_review(account.id, RoleReview.PENDING, NOW, None)


async def test_existing_professional_accounts_wait_for_review_after_the_migration(
    migrated_url: URL,
    make_alembic_config: object,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    await asyncio.to_thread(command.downgrade, config, "identity_0002")
    async with session_factory() as session, session.begin():
        for email, role, tenant in (
            ("p@example.com", "pharmacist", uuid4()),
            ("x@example.com", "patient", None),
        ):
            await session.execute(
                text(
                    "INSERT INTO identity.users (id, email, password_hash, role, tenant_id, "
                    "created_at, email_verified_at) VALUES (:id, :e, 'h', :r, :t, :n, :n)"
                ),
                {"id": uuid4(), "e": email, "r": role, "t": tenant, "n": NOW},
            )
    await asyncio.to_thread(command.upgrade, config, "identity@head")

    users = PostgresUserRepository(session_factory)
    pharmacist, patient = (
        await users.by_email("p@example.com"),
        await users.by_email("x@example.com"),
    )
    assert pharmacist is not None
    assert patient is not None
    assert pharmacist.role_review is RoleReview.PENDING
    assert patient.role_review is RoleReview.NOT_NEEDED


async def test_the_identity_migration_is_reversible(
    migrated_url: URL, make_alembic_config: object
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    await asyncio.to_thread(command.downgrade, config, "identity@base")
    await asyncio.to_thread(command.upgrade, config, "identity@head")
