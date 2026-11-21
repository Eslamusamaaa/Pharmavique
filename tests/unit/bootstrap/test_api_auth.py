"""Account endpoints and the role guard, with in-memory stores and the real token signing."""

import re
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime
from typing import Annotated
from uuid import UUID

import httpx
import pytest
from fastapi import Depends

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.api_auth import require_roles
from pharmavique.foundation.clock import SystemClock
from pharmavique.identity.application.ports import CodeRecord, RefreshRecord
from pharmavique.identity.application.service import IdentityService
from pharmavique.identity.domain.user import User
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.email import EmailError, EmailMessage
from pharmavique.shared_kernel.principal import Principal, Role

GOOD = "a long enough password"


class Users:
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


class Codes:
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


class Outbox:
    """Collects the emails the API sends; can be told to fail like a broken mail server."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self.fail = False

    async def send(self, message: EmailMessage) -> None:
        if self.fail:
            raise EmailError("mail server down")
        self.sent.append(message)

    def last_code(self) -> str:
        found = re.search(r"\b(\d{6})\b", self.sent[-1].text)
        assert found is not None
        return found.group(1)


class Sessions:
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


class QuickHasher:
    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password: str, stored: str) -> bool:
        return stored == f"hashed:{password}"


@pytest.fixture
def outbox() -> Outbox:
    return Outbox()


@pytest.fixture
async def client(outbox: Outbox) -> AsyncIterator[httpx.AsyncClient]:
    tokens = JwtAccessTokens("k" * 40)
    service = IdentityService(
        Users(), Sessions(), QuickHasher(), tokens, SystemClock(), Codes(), b"k" * 32
    )
    app = create_app(
        identity=service, token_verifier=tokens, email_sender=outbox, rate_limit_per_minute=0
    )

    @app.get("/test/company-only")
    async def company_only(
        principal: Annotated[Principal, Depends(require_roles(Role.COMPANY))],
    ) -> dict[str, str]:
        return {"user": str(principal.user_id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def register(
    client: httpx.AsyncClient, email: str = "ana@example.com", role: str = "patient"
):
    return await client.post(
        "/v1/auth/register", json={"email": email, "password": GOOD, "role": role}
    )


async def sign_up(
    client: httpx.AsyncClient,
    outbox: Outbox,
    email: str = "ana@example.com",
    role: str = "patient",
) -> httpx.Response:
    """Sign up and confirm the address with the code the API emailed."""
    assert (await register(client, email, role)).status_code == 201
    return await client.post(
        "/v1/auth/verify-email", json={"email": email, "code": outbox.last_code()}
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_sign_up_returns_no_session_only_the_news_that_a_code_was_sent(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    response = await register(client)

    assert response.status_code == 201
    assert response.json() == {"email": "ana@example.com", "verification_required": True}
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text
    assert len(outbox.sent) == 1
    assert outbox.sent[0].to == "ana@example.com"


async def test_the_emailed_code_gives_a_session_the_caller_can_use(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    await register(client)

    response = await client.post(
        "/v1/auth/verify-email", json={"email": "ana@example.com", "code": outbox.last_code()}
    )
    body = response.json()

    assert response.status_code == 200
    assert body["user"]["email"] == "ana@example.com"
    assert body["user"]["role"] == "patient"
    assert body["user"]["email_verified"] is True
    assert body["expires_in"] == 900
    me = await client.get("/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]
    assert me.json()["email_verified"] is True


async def test_the_password_is_never_sent_back(client: httpx.AsyncClient, outbox: Outbox) -> None:
    text = (await register(client)).text

    assert GOOD not in text
    assert "password" not in text


async def test_the_same_email_twice_is_a_409(client: httpx.AsyncClient, outbox: Outbox) -> None:
    await register(client)

    assert (await register(client)).status_code == 409


async def test_a_weak_password_or_bad_email_is_a_422(client: httpx.AsyncClient) -> None:
    weak = await client.post(
        "/v1/auth/register", json={"email": "a@example.com", "password": "short", "role": "patient"}
    )
    bad = await client.post(
        "/v1/auth/register", json={"email": "nope", "password": GOOD, "role": "patient"}
    )

    assert weak.status_code == 422
    assert bad.status_code == 422


async def test_the_operator_role_cannot_be_chosen_at_sign_up(client: httpx.AsyncClient) -> None:
    assert (await register(client, role="operator")).status_code == 422


async def test_login_works_and_a_wrong_password_is_a_401(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    await sign_up(client, outbox)

    good = await client.post("/v1/auth/login", json={"email": "ana@example.com", "password": GOOD})
    bad = await client.post(
        "/v1/auth/login", json={"email": "ana@example.com", "password": "wrong password!!"}
    )
    unknown = await client.post(
        "/v1/auth/login", json={"email": "no@example.com", "password": GOOD}
    )

    assert good.status_code == 200
    assert bad.status_code == 401
    assert unknown.status_code == 401
    assert bad.json() == unknown.json()  # a wrong email and a wrong password look the same


async def test_refresh_swaps_the_token_and_the_old_one_dies(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    first = (await sign_up(client, outbox)).json()

    second = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    again = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})

    assert second.status_code == 200
    assert again.status_code == 401


async def test_logout_ends_the_session(client: httpx.AsyncClient, outbox: Outbox) -> None:
    first = (await sign_up(client, outbox)).json()

    out = await client.post("/v1/auth/logout", json={"refresh_token": first["refresh_token"]})
    after = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})

    assert out.status_code == 204
    assert after.status_code == 401


async def test_me_needs_a_valid_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/auth/me")).status_code == 401
    assert (await client.get("/v1/auth/me", headers=bearer("garbage"))).status_code == 401


async def test_deleting_the_account_removes_it(client: httpx.AsyncClient, outbox: Outbox) -> None:
    token = (await sign_up(client, outbox)).json()["access_token"]

    assert (await client.delete("/v1/auth/me", headers=bearer(token))).status_code == 204
    assert (await client.get("/v1/auth/me", headers=bearer(token))).status_code == 401
    login = await client.post("/v1/auth/login", json={"email": "ana@example.com", "password": GOOD})
    assert login.status_code == 401


async def test_a_role_guard_lets_only_that_role_in(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    patient = (await sign_up(client, outbox, "p@example.com", "patient")).json()["access_token"]
    company = (await sign_up(client, outbox, "c@example.com", "company")).json()["access_token"]

    assert (await client.get("/test/company-only")).status_code == 401
    assert (await client.get("/test/company-only", headers=bearer(patient))).status_code == 403
    assert (await client.get("/test/company-only", headers=bearer(company))).status_code == 200


async def test_without_accounts_configured_the_endpoints_say_so() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        register = await c.post(
            "/v1/auth/register",
            json={"email": "a@example.com", "password": GOOD, "role": "patient"},
        )
        assert register.status_code == 503
        assert (await c.get("/v1/auth/me")).status_code == 503


# ---- confirming the email ---------------------------------------------------------------------
async def test_a_wrong_code_is_a_400_and_the_right_one_still_works(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    await register(client)
    right = outbox.last_code()
    wrong = "000000" if right != "000000" else "111111"

    bad = await client.post(
        "/v1/auth/verify-email", json={"email": "ana@example.com", "code": wrong}
    )
    good = await client.post(
        "/v1/auth/verify-email", json={"email": "ana@example.com", "code": right}
    )

    assert bad.status_code == 400
    assert good.status_code == 200


async def test_too_many_wrong_codes_are_a_429(client: httpx.AsyncClient, outbox: Outbox) -> None:
    await register(client)
    wrong = "000000" if outbox.last_code() != "000000" else "111111"

    statuses = [
        (
            await client.post(
                "/v1/auth/verify-email", json={"email": "ana@example.com", "code": wrong}
            )
        ).status_code
        for _ in range(6)
    ]

    assert statuses[:4] == [400, 400, 400, 400]
    assert set(statuses[4:]) == {429}


async def test_sign_in_before_confirming_is_a_403_that_says_why(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    await register(client)

    response = await client.post(
        "/v1/auth/login", json={"email": "ana@example.com", "password": GOOD}
    )
    wrong = await client.post(
        "/v1/auth/login", json={"email": "ana@example.com", "password": "wrong password!!"}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "email_not_verified"}
    assert wrong.status_code == 401  # a wrong password never reveals the account exists


async def test_asking_for_a_code_gives_the_same_answer_for_any_address(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    await register(client)
    sent_before = len(outbox.sent)

    known = await client.post("/v1/auth/resend-code", json={"email": "ana@example.com"})
    unknown = await client.post("/v1/auth/resend-code", json={"email": "nobody@example.com"})
    garbage = await client.post("/v1/auth/resend-code", json={"email": "not-an-email"})

    assert known.status_code == unknown.status_code == garbage.status_code == 202
    assert known.json() == unknown.json() == garbage.json()
    assert len(outbox.sent) == sent_before  # too soon after sign-up: nothing more was sent


async def test_a_failing_mail_server_does_not_break_sign_up(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    outbox.fail = True

    response = await register(client)

    assert response.status_code == 201  # the person can ask for a new code later
    assert outbox.sent == []


async def test_email_notifications_can_be_switched_off(
    client: httpx.AsyncClient, outbox: Outbox
) -> None:
    token = (await sign_up(client, outbox)).json()["access_token"]

    off = await client.put(
        "/v1/auth/me/notifications", json={"email": False}, headers=bearer(token)
    )
    me = await client.get("/v1/auth/me", headers=bearer(token))

    assert off.status_code == 204
    assert me.json()["email_notifications"] is False
    assert (await client.put("/v1/auth/me/notifications", json={"email": True})).status_code == 401
