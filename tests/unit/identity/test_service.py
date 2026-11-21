"""Sign-up, sign-in, refresh rotation and replay detection, with in-memory adapters."""

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from pharmavique.identity.application.ports import CodeRecord, RefreshRecord
from pharmavique.identity.application.service import IdentityService, Session
from pharmavique.identity.domain.user import (
    CODE_MAX_ATTEMPTS,
    CODE_MAX_PER_HOUR,
    CODE_RESEND_SECONDS,
    CODE_TTL_MINUTES,
    CodeLocked,
    EmailNotVerified,
    EmailTaken,
    InvalidCode,
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

    async def mark_verified(self, user_id: UUID, at: datetime) -> None:
        for email, user in self.by.items():
            if user.id == user_id:
                self.by[email] = replace(user, email_verified_at=at)

    async def set_email_notifications(self, user_id: UUID, enabled: bool) -> bool:
        for email, user in self.by.items():
            if user.id == user_id:
                self.by[email] = replace(user, email_notifications=enabled)
                return True
        return False


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


class FakeCodes:
    def __init__(self) -> None:
        self.records: list[CodeRecord] = []
        self.consumed: set[object] = set()

    async def add(self, record: CodeRecord) -> None:
        self.consumed |= {r.id for r in self.records if r.user_id == record.user_id}
        self.records.append(record)

    async def latest(self, user_id: UUID) -> CodeRecord | None:
        mine = [r for r in self.records if r.user_id == user_id and r.id not in self.consumed]
        return mine[-1] if mine else None

    async def add_attempt(self, code_id: object) -> int:
        for i, r in enumerate(self.records):
            if r.id == code_id:
                self.records[i] = replace(r, attempts=r.attempts + 1)
                return self.records[i].attempts
        return 0

    async def consume(self, code_id: object) -> bool:
        if code_id in self.consumed:
            return False
        self.consumed.add(code_id)
        return True

    async def count_since(self, user_id: UUID, since: datetime) -> int:
        return len([r for r in self.records if r.user_id == user_id and r.created_at >= since])


KEY = b"k" * 32
CODES: dict[int, FakeCodes] = {}


def service() -> tuple[IdentityService, FakeUsers, FakeSessions, FakeClock]:
    users, sessions, clock, codes = FakeUsers(), FakeSessions(), FakeClock(), FakeCodes()
    svc = IdentityService(users, sessions, FakeHasher(), FakeTokens(), clock, codes, KEY)
    CODES[id(svc)] = codes
    return svc, users, sessions, clock


def code_in(text: str) -> str:
    found = re.search(r"\b(\d{6})\b", text)
    assert found is not None
    return found.group(1)


async def sign_up(
    svc: IdentityService, email: str, password: str = GOOD, role: Role = Role.PATIENT
) -> Session:
    """Sign up and confirm the address with the code that was emailed."""
    registration = await svc.register(email, password, role)
    return await svc.verify_email(email, code_in(registration.email.text))


async def test_sign_up_creates_a_user_and_a_session() -> None:
    svc, users, sessions, _ = service()

    session = await sign_up(svc, "  Ana@Example.COM ", GOOD, Role.PATIENT)

    assert session.user.email == "ana@example.com"
    assert session.user.role is Role.PATIENT
    assert session.user.tenant_id is None
    assert session.expires_in == 900
    assert "ana@example.com" in users.by
    assert len(sessions.records) == 1


async def test_a_pharmacist_and_a_company_get_a_tenant_a_patient_does_not() -> None:
    svc, *_ = service()

    pharmacist = await sign_up(svc, "p@example.com", GOOD, Role.PHARMACIST)
    company = await sign_up(svc, "c@example.com", GOOD, Role.COMPANY)
    patient = await sign_up(svc, "x@example.com", GOOD, Role.PATIENT)

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
    await sign_up(svc, "ana@example.com", GOOD, Role.PATIENT)

    with pytest.raises(EmailTaken):
        await svc.register("ANA@example.com", GOOD, Role.PHARMACIST)


async def test_login_with_the_right_password_opens_a_session() -> None:
    svc, *_ = service()
    await sign_up(svc, "ana@example.com", GOOD, Role.PATIENT)

    session = await svc.login("Ana@example.com", GOOD)

    assert session.user.email == "ana@example.com"


@pytest.mark.parametrize(
    ("email", "password"),
    [("ana@example.com", "wrong password here"), ("nobody@example.com", GOOD), ("bad", GOOD)],
)
async def test_a_wrong_email_or_password_is_the_same_failure(email: str, password: str) -> None:
    svc, *_ = service()
    await sign_up(svc, "ana@example.com", GOOD, Role.PATIENT)

    with pytest.raises(InvalidCredentials):
        await svc.login(email, password)


async def test_refresh_gives_a_new_session_and_the_old_token_stops_working() -> None:
    svc, *_ = service()
    first = await sign_up(svc, "ana@example.com", GOOD, Role.PATIENT)

    second = await svc.refresh(first.refresh_token)

    assert second.refresh_token != first.refresh_token
    with pytest.raises(SessionRejected):
        await svc.refresh(first.refresh_token)


async def test_a_replayed_refresh_token_ends_every_session_of_that_user() -> None:
    svc, *_ = service()
    first = await sign_up(svc, "ana@example.com", GOOD, Role.PATIENT)
    second = await svc.refresh(first.refresh_token)

    with pytest.raises(SessionRejected):
        await svc.refresh(first.refresh_token)  # the old token comes back: a replay

    with pytest.raises(SessionRejected):
        await svc.refresh(second.refresh_token)  # the newer token was revoked as well


async def test_an_expired_refresh_token_is_rejected() -> None:
    svc, _, _, clock = service()
    first = await sign_up(svc, "ana@example.com", GOOD, Role.PATIENT)
    clock.current = NOW + timedelta(days=31)

    with pytest.raises(SessionRejected):
        await svc.refresh(first.refresh_token)


async def test_an_unknown_refresh_token_is_rejected() -> None:
    svc, *_ = service()

    with pytest.raises(SessionRejected):
        await svc.refresh("made-up")


async def test_logout_revokes_the_refresh_token() -> None:
    svc, *_ = service()
    first = await sign_up(svc, "ana@example.com", GOOD, Role.PATIENT)

    await svc.logout(first.refresh_token)

    with pytest.raises(SessionRejected):
        await svc.refresh(first.refresh_token)


async def test_deleting_the_account_removes_the_user() -> None:
    svc, users, _, _ = service()
    session = await sign_up(svc, "ana@example.com", GOOD, Role.PATIENT)

    await svc.delete_account(session.user.id)

    assert users.by == {}
    assert await svc.profile(session.user.id) is None


# ---- confirming the email ---------------------------------------------------------------------
async def register_for_code(svc: IdentityService, email: str = "ana@example.com") -> str:
    registration = await svc.register(email, GOOD, Role.PATIENT)
    assert registration.email.to == email
    return code_in(registration.email.text)


async def test_sign_up_makes_an_unconfirmed_account_and_no_session() -> None:
    svc, users, sessions, _ = service()

    registration = await svc.register("  Ana@Example.COM ", GOOD, Role.PATIENT)

    assert registration.user.email == "ana@example.com"
    assert registration.user.email_verified is False
    assert registration.email.to == "ana@example.com"
    assert sessions.records == {}  # no session until the code is entered
    assert users.by["ana@example.com"].email_verified_at is None


async def test_the_emailed_code_confirms_the_account_and_opens_the_first_session() -> None:
    svc, users, sessions, _ = service()
    code = await register_for_code(svc)

    session = await svc.verify_email("ana@example.com", code)

    assert session.user.email_verified is True
    assert users.by["ana@example.com"].email_verified_at == NOW
    assert len(sessions.records) == 1


async def test_the_code_is_six_digits_and_the_email_says_how_long_it_lasts() -> None:
    svc, *_ = service()
    registration = await svc.register("ana@example.com", GOOD, Role.PATIENT)
    assert re.fullmatch(r"\d{6}", code_in(registration.email.text))
    assert str(CODE_TTL_MINUTES) in registration.email.text
    assert "ana@example.com" not in registration.email.text  # nothing personal inside the body


async def test_only_a_keyed_hash_of_the_code_is_stored() -> None:
    svc, *_ = service()
    code = await register_for_code(svc)
    (stored,) = CODES[id(svc)].records
    assert code not in stored.code_hash
    assert len(stored.code_hash) == 64


async def test_a_wrong_code_is_refused_and_counted() -> None:
    svc, *_ = service()
    code = await register_for_code(svc)
    wrong = "000000" if code != "000000" else "111111"

    with pytest.raises(InvalidCode):
        await svc.verify_email("ana@example.com", wrong)
    assert CODES[id(svc)].records[-1].attempts == 1
    await svc.verify_email("ana@example.com", code)  # the right one still works


async def test_too_many_wrong_codes_lock_that_code_even_for_the_right_one() -> None:
    svc, *_ = service()
    code = await register_for_code(svc)
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(CODE_MAX_ATTEMPTS - 1):
        with pytest.raises(InvalidCode):
            await svc.verify_email("ana@example.com", wrong)
    with pytest.raises(CodeLocked):
        await svc.verify_email("ana@example.com", wrong)
    with pytest.raises(CodeLocked):
        await svc.verify_email("ana@example.com", code)


async def test_an_expired_code_is_refused() -> None:
    svc, _, _, clock = service()
    code = await register_for_code(svc)
    clock.current = NOW + timedelta(minutes=CODE_TTL_MINUTES + 1)

    with pytest.raises(InvalidCode):
        await svc.verify_email("ana@example.com", code)


async def test_a_code_works_once() -> None:
    svc, *_ = service()
    code = await register_for_code(svc)
    await svc.verify_email("ana@example.com", code)

    with pytest.raises(InvalidCode):
        await svc.verify_email("ana@example.com", code)


async def test_a_code_for_an_unknown_or_malformed_address_is_just_invalid() -> None:
    svc, *_ = service()
    with pytest.raises(InvalidCode):
        await svc.verify_email("nobody@example.com", "123456")
    with pytest.raises(InvalidCode):
        await svc.verify_email("not-an-email", "123456")


async def test_sign_in_with_the_right_password_before_confirming_says_so() -> None:
    svc, *_ = service()
    await svc.register("ana@example.com", GOOD, Role.PATIENT)

    with pytest.raises(EmailNotVerified):
        await svc.login("ana@example.com", GOOD)


async def test_a_wrong_password_on_an_unconfirmed_account_does_not_reveal_it_exists() -> None:
    svc, *_ = service()
    await svc.register("ana@example.com", GOOD, Role.PATIENT)

    with pytest.raises(InvalidCredentials):
        await svc.login("ana@example.com", "wrong password here")


async def test_the_operator_made_by_the_command_can_sign_in_at_once() -> None:
    svc, *_ = service()
    await svc.create_operator("o@example.com", GOOD)

    session = await svc.login("o@example.com", GOOD)

    assert session.user.role is Role.OPERATOR


# ---- asking for a new code --------------------------------------------------------------------
async def test_a_new_code_replaces_the_old_one_after_the_wait() -> None:
    svc, _, _, clock = service()
    old = await register_for_code(svc)
    clock.current = NOW + timedelta(seconds=CODE_RESEND_SECONDS + 1)

    message = await svc.resend_code("ana@example.com")

    assert message is not None
    fresh = code_in(message.text)
    if fresh != old:
        with pytest.raises(InvalidCode):
            await svc.verify_email("ana@example.com", old)  # the old code was retired
    await svc.verify_email("ana@example.com", fresh)


async def test_asking_again_too_soon_sends_nothing() -> None:
    svc, *_ = service()
    await register_for_code(svc)

    assert await svc.resend_code("ana@example.com") is None


async def test_at_most_a_few_codes_an_hour() -> None:
    svc, _, _, clock = service()
    await register_for_code(svc)
    sent = 1
    for _ in range(CODE_MAX_PER_HOUR + 2):
        clock.current += timedelta(seconds=CODE_RESEND_SECONDS + 1)
        if await svc.resend_code("ana@example.com") is not None:
            sent += 1
    assert sent == CODE_MAX_PER_HOUR


@pytest.mark.parametrize("email", ["nobody@example.com", "not-an-email"])
async def test_asking_for_a_code_for_an_unknown_address_sends_nothing_and_says_nothing(
    email: str,
) -> None:
    svc, *_ = service()
    assert await svc.resend_code(email) is None


async def test_a_confirmed_account_is_not_sent_codes() -> None:
    svc, _, _, clock = service()
    await sign_up(svc, "ana@example.com")
    clock.current = NOW + timedelta(minutes=5)
    assert await svc.resend_code("ana@example.com") is None


async def test_email_notifications_can_be_switched_off_and_on() -> None:
    svc, users, *_ = service()
    session = await sign_up(svc, "ana@example.com")
    assert users.by["ana@example.com"].email_notifications is True

    assert await svc.set_email_notifications(session.user.id, False) is True
    assert users.by["ana@example.com"].email_notifications is False
    profile = await svc.profile(session.user.id)
    assert profile is not None
    assert profile.email_notifications is False
