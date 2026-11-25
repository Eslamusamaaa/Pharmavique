"""The access-token signing secret: production refuses to start without a strong one (ADR-020)."""

import logging

import pytest
from pydantic import SecretStr

from pharmavique.bootstrap.settings import MIN_JWT_SECRET_LENGTH, Settings, check_signing_secret


def settings(environment: str, secret: str | None) -> Settings:
    return Settings(
        _env_file=None,
        environment=environment,
        jwt_secret=SecretStr(secret) if secret is not None else None,
    )


@pytest.mark.parametrize("secret", [None, "short", "x" * (MIN_JWT_SECRET_LENGTH - 1)])
def test_production_refuses_a_missing_or_short_secret(secret: str | None) -> None:
    with pytest.raises(RuntimeError, match="PHARMAVIQUE_JWT_SECRET"):
        check_signing_secret(settings("prod", secret))


def test_production_accepts_a_long_secret() -> None:
    check_signing_secret(settings("prod", "x" * MIN_JWT_SECRET_LENGTH))


def test_the_error_never_shows_the_secret() -> None:
    with pytest.raises(RuntimeError) as raised:
        check_signing_secret(settings("prod", "my-short-secret"))
    assert "my-short-secret" not in str(raised.value)


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_development_only_warns(environment: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        check_signing_secret(settings(environment, None))
    assert "PHARMAVIQUE_JWT_SECRET" in caplog.text


def test_a_long_secret_in_development_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        check_signing_secret(settings("dev", "x" * MIN_JWT_SECRET_LENGTH))
    assert caplog.text == ""
