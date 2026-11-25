"""Which routes need an account (owner's decision, 2026-11-25).

Public registry data (search, drug pages, alternatives, pharmacies, sources) stays open. Anything
that runs a paid or rate-limited model (assistant, scans, voice) and anything personal needs a
signed-in account. Every route must be listed here, so a new route forces a decision.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.features import Features, get_features
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.principal import Principal, Role

PUBLIC = {
    ("GET", "/health"),
    # Request counts and timings only, no personal data (also the rate-limit tests' probe).
    ("GET", "/metrics"),
    ("GET", "/v1/features"),
    ("POST", "/v1/auth/register"),
    ("POST", "/v1/auth/verify-email"),
    ("POST", "/v1/auth/resend-code"),
    ("GET", "/v1/auth/unsubscribe"),
    ("POST", "/v1/auth/unsubscribe"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/refresh"),
    ("POST", "/v1/auth/logout"),
    ("GET", "/v1/search"),
    ("GET", "/v1/products/{register_number}"),
    ("GET", "/v1/products/{register_number}/details"),
    ("GET", "/v1/products/{register_number}/same-ingredient"),
    ("GET", "/v1/products/{register_number}/similar-names"),
    ("GET", "/v1/products/{register_number}/picture"),
    ("GET", "/v1/products/{register_number}/shortage"),
    ("GET", "/v1/compare"),
    ("GET", "/v1/ingredients"),
    ("POST", "/v1/pharmacies/nearby"),
    ("GET", "/v1/pharmacies/cities"),
    ("GET", "/v1/pharmacies"),
    ("POST", "/v1/interactions/check"),
    ("GET", "/v1/interactions/contraindications/{register_number}"),
    # A one-time, short-lived link to a spoken answer: an <audio> element cannot send a token.
    ("GET", "/v1/voice/audio/{key}"),
    # The job id is a long random ticket handed only to whoever submitted the job.
    ("GET", "/v1/jobs/{job_id}"),
}

# Paid or rate-limited models: an account is needed while the `login_for_ai` feature is on.
AI = {
    ("POST", "/v1/assistant/ask"),
    ("POST", "/v1/recognition/scan"),
    ("POST", "/v1/voice/transcribe"),
    ("POST", "/v1/voice/speak"),
    ("POST", "/v1/voice/drug-name"),
    ("POST", "/v1/jobs/scan"),
    ("POST", "/v1/jobs/assistant"),
}

ROLE_ONLY = {
    ("GET", "/v1/company/market"): Role.COMPANY,
    ("GET", "/v1/company/gaps"): Role.COMPANY,
    ("GET", "/v1/company/radar"): Role.COMPANY,
    ("GET", "/v1/operator/quality"): Role.OPERATOR,
    ("GET", "/v1/operator/accounts/pending"): Role.OPERATOR,
    ("POST", "/v1/operator/accounts/{user_id}/review"): Role.OPERATOR,
    ("GET", "/v1/me/shelf"): Role.PHARMACIST,
    ("POST", "/v1/me/shelf"): Role.PHARMACIST,
    ("DELETE", "/v1/me/shelf/{register_number}"): Role.PHARMACIST,
}

REQUIRED = {"current_principal", "signed_in_for_ai", "require_roles.<locals>.check"}

TOKENS = JwtAccessTokens("k" * 40)


def _routes(routes: list[Any]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _routes(route.original_router.routes)


def _calls(dependant: Any) -> set[str]:
    names: set[str] = set()
    for sub in dependant.dependencies:
        names.add(getattr(sub.call, "__qualname__", ""))
        names |= _calls(sub)
    return names


def _operations(app: FastAPI) -> dict[tuple[str, str], set[str]]:
    found: dict[tuple[str, str], set[str]] = {}
    for route in _routes(app.router.routes):
        for method in (route.methods or set()) - {"HEAD", "OPTIONS"}:
            found[(method, route.path)] = _calls(route.dependant)
    return found


def test_every_route_is_classified() -> None:
    operations = _operations(create_app())
    classified = PUBLIC | AI | set(ROLE_ONLY)
    unclassified = {
        op for op, calls in operations.items() if op not in classified and not calls & REQUIRED
    }
    assert unclassified == set(), "decide whether these routes need an account"


def test_public_routes_need_no_account() -> None:
    operations = _operations(create_app())
    for op in PUBLIC:
        assert op in operations, op
        assert not operations[op] & REQUIRED, f"{op} should stay open"


def test_model_routes_need_an_account() -> None:
    operations = _operations(create_app())
    for op in AI:
        assert "signed_in_for_ai" in operations[op], f"{op} must need an account"


def test_role_routes_check_the_role() -> None:
    operations = _operations(create_app())
    for op in ROLE_ONLY:
        assert "require_roles.<locals>.check" in operations[op], f"{op} must check the role"


def _app(login_for_ai: bool) -> FastAPI:
    app = create_app(
        token_verifier=TOKENS,
        rate_limit_per_minute=0,
        heavy_rate_limit_per_minute=0,
    )
    app.dependency_overrides[get_features] = lambda: Features(
        _env_file=None, login_for_ai=login_for_ai
    )
    return app


def _token(role: Role) -> dict[str, str]:
    token, _ = TOKENS.issue(Principal(uuid4(), None, frozenset({role})), datetime.now(UTC))
    return {"Authorization": f"Bearer {token}"}


async def _speak(app: FastAPI, headers: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            "/v1/voice/drug-name", json={"text": "أبغى بنادول"}, headers=headers
        )


async def test_a_guest_is_asked_to_sign_in_before_using_a_model() -> None:
    response = await _speak(_app(login_for_ai=True))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_a_signed_in_patient_gets_through() -> None:
    response = await _speak(_app(login_for_ai=True), _token(Role.PATIENT))
    assert response.status_code == 200


async def test_with_the_feature_off_a_guest_gets_through_as_before() -> None:
    response = await _speak(_app(login_for_ai=False))
    assert response.status_code == 200


async def test_a_broken_token_is_refused_even_with_the_feature_off() -> None:
    response = await _speak(_app(login_for_ai=False), {"Authorization": "Bearer nonsense-token"})
    assert response.status_code == 401


@pytest.mark.parametrize(("op", "role"), list(ROLE_ONLY.items()))
async def test_a_patient_is_refused_on_role_routes(op: tuple[str, str], role: Role) -> None:
    method, path = op
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(login_for_ai=True)), base_url="http://test"
    ) as client:
        url = path.replace("{register_number}", "1").replace(
            "{user_id}", "00000000-0000-0000-0000-000000000000"
        )
        anonymous = await client.request(method, url)
        patient = await client.request(method, url, headers=_token(Role.PATIENT))
    assert anonymous.status_code in {401, 503}  # 503 only when a store runs before the check
    assert patient.status_code in {403, 503}
