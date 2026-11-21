"""Sign-up, sign-in, refresh rotation and replay detection, with in-memory adapters."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from pharmavique.identity.application.ports import RefreshRecord
from pharmavique.identity.application.service import IdentityService
from pharmavique.identity.domain.user import (
    EmailTaken,
    InvalidCredentials,
    SessionRejected,
    User,
)
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.principal import Principal, Role

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
GOOD = "a long enough password"


class FakeClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


class FakeUsers:
    def __init__(self) -> None:
        self.by: dict[str, User] = {}

    async def add(self, user: User) -> bool:
        if user.email in self.by:
            return False
        self.by[user.email] = user
        return True

    async def by_email(self, email: str) -> User | None:
        return self.by.get(email)

    async def by_id(self, user_id: UUID) -> User | None:
        return next((u for u in self.by.values() if u.id == user_id), None)

    async def delete(self, user_id: UUID) -> None:
        self.by = {e: u for e, u in self.by.items() if u.id != user_id}


class FakeSessions:
    def __init__(self) -> None:
        self.records: dict[str, RefreshRecord] = {}
        self.used: set[str] = set()

    async def save(self, record: RefreshRecord) -> None:
        self.records[record.token_hash] = record

    async def find(self, token_hash: str) -> RefreshRecord | None:
        return self.records.get(token_hash)

    async def mark_used(self, token_hash: str) -> bool:
        if token_hash in self.used:
            return False
        self.used.add(token_hash)
        return True

    async def revoke_user(self, user_id: UUID) -> None:
        self.records = {h: r for h, r in self.records.items() if r.user_id != user_id}

    async def revoke(self, token_hash: str) -> None:
        self.records.pop(token_hash, None)


class FakeHasher:
    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password: str, stored: str) -> bool:
        return stored == f"hashed:{password}"


class FakeTokens:
    def issue(self, principal: Principal, now: datetime) -> tuple[str, int]:
        return f"access-for-{principal.user_id}", 900

    def verify(self, token: str, now: datetime) -> Principal | None:
        return None


def service() -> tuple[IdentityService, FakeUsers, FakeSessions, FakeClock]:
    users, sessions, clock = FakeUsers(), FakeSessions(), FakeClock()
    svc = IdentityService(users, sessions, FakeHasher(), FakeTokens(), clock)
    return svc, users, sessions, clock


async def test_sign_up_creates_a_user_and_a_session() -> None:
    svc, users, sessions, _ = service()

    session = await svc.register("  Ana@Example.COM ", GOOD, Role.PATIENT)

    assert session.user.email == "ana@example.com"
    assert session.user.role is Role.PATIENT
    assert session.user.tenant_id is None
    assert session.expires_in == 900
    assert "ana@example.com" in users.by
    assert len(sessions.records) == 1


async def test_a_pharmacist_and_a_company_get_a_tenant_a_patient_does_not() -> None:
    svc, *_ = service()

    pharmacist = await svc.register("p@example.com", GOOD, Role.PHARMACIST)
    company = await svc.register("c@example.com", GOOD, Role.COMPANY)
    patient = await svc.register("x@example.com", GOOD, Role.PATIENT)

    assert pharmacist.user.tenant_id is not None
    assert company.user.tenant_id is not None
    assert pharmacist.user.tenant_id != company.user.tenant_id
    assert patient.user.tenant_id is None


async def test_the_operator_role_cannot_be_chosen_at_sign_up() -> None:
    svc, *_ = service()

    with pytest.raises(InvariantViolation):
        await svc.register("o@example.com", GOOD, Role.OPERATOR)


async def test_the_operator_is_made_by_a_command() -> None:
    svc, users, _, _ = service()

    view = await svc.create_operator("o@example.com", GOOD)

    assert view.role is Role.OPERATOR
    assert users.by["o@example.com"].role is Role.OPERATOR


@pytest.mark.parametrize("email", ["", "not-an-email", "a@b", "a b@example.com"])
async def test_a_bad_email_is_rejected(email: str) -> None:
    svc, *_ = service()

    with pytest.raises(InvariantViolation):
        await svc.register(email, GOOD, Role.PATIENT)


@pytest.mark.parametrize("password", ["short", "x" * 201, "ana@example.com"])
async def test_a_weak_password_is_rejected(password: str) -> None:
    svc, *_ = service()

    with pytest.raises(InvariantViolation):
        await svc.register("ana@example.com", password, Role.PATIENT)


async def test_the_same_email_cannot_sign_up_twice() -> None:
    svc, *_ = service()
    await svc.register("ana@example.com", GOOD, Role.PATIENT)

    with pytest.raises(EmailTaken):
        await svc.register("ANA@example.com", GOOD, Role.PHARMACIST)


async def test_login_with_the_right_password_opens_a_session() -> None:
    svc, *_ = service()
    await svc.register("ana@example.com", GOOD, Role.PATIENT)

    session = await svc.login("Ana@example.com", GOOD)

    assert session.user.email == "ana@example.com"


@pytest.mark.parametrize(
    ("email", "password"),
    [("ana@example.com", "wrong password here"), ("nobody@example.com", GOOD), ("bad", GOOD)],
)
async def test_a_wrong_email_or_password_is_the_same_failure(email: str, password: str) -> None:
    svc, *_ = service()
    await svc.register("ana@example.com", GOOD, Role.PATIENT)

    with pytest.raises(InvalidCredentials):
        await svc.login(email, password)


async def test_refresh_gives_a_new_session_and_the_old_token_stops_working() -> None:
    svc, *_ = service()
    first = await svc.register("ana@example.com", GOOD, Role.PATIENT)

    second = await svc.refresh(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    with pytest.raises(SessionRejected):
        await svc.refresh(first.refresh_token)


async def test_a_replayed_refresh_token_ends_every_session_of_that_user() -> None:
    svc, *_ = service()
    first = await svc.register("ana@example.com", GOOD, Role.PATIENT)
    second = await svc.refresh(first.refresh_token)

    with pytest.raises(SessionRejected):
        await svc.refresh(first.refresh_token)  # the old token comes back: a replay

    with pytest.raises(SessionRejected):
        await svc.refresh(second.refresh_token)  # the newer token was revoked as well


async def test_an_expired_refresh_token_is_rejected() -> None:
    svc, _, _, clock = service()
    first = await svc.register("ana@example.com", GOOD, Role.PATIENT)
    clock.current = NOW + timedelta(days=31)

    with pytest.raises(SessionRejected):
        await svc.refresh(first.refresh_token)


async def test_an_unknown_refresh_token_is_rejected() -> None:
    svc, *_ = service()

    with pytest.raises(SessionRejected):
        await svc.refresh("made-up")


async def test_logout_revokes_the_refresh_token() -> None:
    svc, *_ = service()
    first = await svc.register("ana@example.com", GOOD, Role.PATIENT)

    await svc.logout(first.refresh_token)

    with pytest.raises(SessionRejected):
        await svc.refresh(first.refresh_token)


async def test_deleting_the_account_removes_the_user() -> None:
    svc, users, _, _ = service()
    session = await svc.register("ana@example.com", GOOD, Role.PATIENT)

    await svc.delete_account(session.user.id)

    assert users.by == {}
    assert await svc.profile(session.user.id) is None
