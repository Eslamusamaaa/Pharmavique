"""Account endpoints and the role guard, with in-memory stores and the real token signing."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx
import pytest
from fastapi import Depends

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.api_auth import require_roles
from pharmavique.foundation.clock import SystemClock
from pharmavique.identity.application.ports import RefreshRecord
from pharmavique.identity.application.service import IdentityService
from pharmavique.identity.domain.user import User
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
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
async def client() -> AsyncIterator[httpx.AsyncClient]:
    tokens = JwtAccessTokens("k" * 40)
    service = IdentityService(Users(), Sessions(), QuickHasher(), tokens, SystemClock())
    app = create_app(identity=service, token_verifier=tokens)

    @app.get("/test/company-only")
    async def company_only(
        principal: Annotated[Principal, Depends(require_roles(Role.COMPANY))],
    ) -> dict[str, str]:
        return {"user": str(principal.user_id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def sign_up(client: httpx.AsyncClient, email: str = "ana@example.com", role: str = "patient"):
    return await client.post(
        "/v1/auth/register", json={"email": email, "password": GOOD, "role": role}
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_sign_up_returns_a_session_the_caller_can_use(client: httpx.AsyncClient) -> None:
    response = await sign_up(client)
    body = response.json()

    assert response.status_code == 201
    assert body["user"]["email"] == "ana@example.com"
    assert body["user"]["role"] == "patient"
    assert body["expires_in"] == 900
    me = await client.get("/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


async def test_the_password_is_never_sent_back(client: httpx.AsyncClient) -> None:
    text = (await sign_up(client)).text

    assert GOOD not in text
    assert "password" not in text


async def test_the_same_email_twice_is_a_409(client: httpx.AsyncClient) -> None:
    await sign_up(client)

    assert (await sign_up(client)).status_code == 409


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
    assert (await sign_up(client, role="operator")).status_code == 422


async def test_login_works_and_a_wrong_password_is_a_401(client: httpx.AsyncClient) -> None:
    await sign_up(client)

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


async def test_refresh_swaps_the_token_and_the_old_one_dies(client: httpx.AsyncClient) -> None:
    first = (await sign_up(client)).json()

    second = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    again = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})

    assert second.status_code == 200
    assert again.status_code == 401


async def test_logout_ends_the_session(client: httpx.AsyncClient) -> None:
    first = (await sign_up(client)).json()

    out = await client.post("/v1/auth/logout", json={"refresh_token": first["refresh_token"]})
    after = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})

    assert out.status_code == 204
    assert after.status_code == 401


async def test_me_needs_a_valid_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/auth/me")).status_code == 401
    assert (await client.get("/v1/auth/me", headers=bearer("garbage"))).status_code == 401


async def test_deleting_the_account_removes_it(client: httpx.AsyncClient) -> None:
    token = (await sign_up(client)).json()["access_token"]

    assert (await client.delete("/v1/auth/me", headers=bearer(token))).status_code == 204
    assert (await client.get("/v1/auth/me", headers=bearer(token))).status_code == 401
    login = await client.post("/v1/auth/login", json={"email": "ana@example.com", "password": GOOD})
    assert login.status_code == 401


async def test_a_role_guard_lets_only_that_role_in(client: httpx.AsyncClient) -> None:
    patient = (await sign_up(client, "p@example.com", "patient")).json()["access_token"]
    company = (await sign_up(client, "c@example.com", "company")).json()["access_token"]

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
