"""scrypt hashing and signed access tokens."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from pharmavique.identity.infrastructure.passwords import (
    ScryptPasswordHasher,
    hash_password,
    verify_password,
)
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.principal import Principal, Role

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
SECRET = "x" * 40


def test_a_password_verifies_against_its_own_hash_only() -> None:
    stored = hash_password("correct horse battery")

    assert verify_password("correct horse battery", stored)
    assert not verify_password("correct horse batterz", stored)


def test_two_hashes_of_the_same_password_differ_by_salt() -> None:
    assert hash_password("same password here") != hash_password("same password here")


@pytest.mark.parametrize(
    "stored", ["", "plain", "scrypt$1$2", "bcrypt$a$b$c$d$e", "scrypt$x$8$1$aa$bb"]
)
def test_a_malformed_stored_hash_never_verifies_or_raises(stored: str) -> None:
    assert verify_password("anything at all", stored) is False


async def test_the_async_hasher_matches_the_plain_functions() -> None:
    hasher = ScryptPasswordHasher()

    stored = await hasher.hash("a long enough password")

    assert await hasher.verify("a long enough password", stored)
    assert not await hasher.verify("another long password", stored)


def principal(role: Role = Role.PHARMACIST, tenant: bool = True) -> Principal:
    return Principal(uuid4(), uuid4() if tenant else None, frozenset({role}))


def test_an_issued_token_gives_back_the_same_caller() -> None:
    tokens = JwtAccessTokens(SECRET)
    who = principal()

    token, seconds = tokens.issue(who, NOW)

    assert seconds == 900
    assert tokens.verify(token, NOW + timedelta(minutes=5)) == who


def test_a_patient_token_has_no_tenant() -> None:
    tokens = JwtAccessTokens(SECRET)
    who = principal(Role.PATIENT, tenant=False)

    token, _ = tokens.issue(who, NOW)

    assert tokens.verify(token, NOW) == who


def test_an_expired_token_is_rejected() -> None:
    tokens = JwtAccessTokens(SECRET)
    token, _ = tokens.issue(principal(), NOW)

    assert tokens.verify(token, NOW + timedelta(minutes=16)) is None


def test_a_token_signed_with_another_secret_is_rejected() -> None:
    token, _ = JwtAccessTokens("y" * 40).issue(principal(), NOW)

    assert JwtAccessTokens(SECRET).verify(token, NOW) is None


def test_a_token_that_says_none_for_its_algorithm_is_rejected() -> None:
    claims = {
        "iss": "pharmavique",
        "sub": str(uuid4()),
        "role": "operator",
        "iat": 1,
        "exp": 4102444800,
    }
    forged = jwt.encode(claims, key="", algorithm="none")

    assert JwtAccessTokens(SECRET).verify(forged, NOW) is None


@pytest.mark.parametrize("token", ["", "abc", "a.b.c"])
def test_garbage_is_rejected(token: str) -> None:
    assert JwtAccessTokens(SECRET).verify(token, NOW) is None


def test_a_short_signing_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="at least"):
        JwtAccessTokens("short")
