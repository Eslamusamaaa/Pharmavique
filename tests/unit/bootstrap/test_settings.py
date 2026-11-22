"""Settings: an environment variable that is set but empty means "not configured"."""

import pytest

from pharmavique.bootstrap.settings import Settings


@pytest.mark.parametrize("name", ["REDIS_URL", "DATABASE_URL", "JWT_SECRET", "GROQ_API_KEY"])
def test_an_empty_variable_is_the_same_as_an_unset_one(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(f"PHARMAVIQUE_{name}", "")
    settings = Settings(_env_file=None)
    assert getattr(settings, name.lower()) is None


def test_a_filled_variable_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHARMAVIQUE_REDIS_URL", "redis://127.0.0.1:6379/0")
    settings = Settings(_env_file=None)
    assert settings.redis_url is not None
    assert settings.redis_url.get_secret_value() == "redis://127.0.0.1:6379/0"


def test_cloudflare_is_configured_only_with_both_a_token_and_an_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHARMAVIQUE_CLOUDFLARE_API_TOKEN", "token")
    monkeypatch.setenv("PHARMAVIQUE_CLOUDFLARE_ACCOUNT_ID", "")
    assert Settings(_env_file=None).cloudflare_base_url is None

    monkeypatch.setenv("PHARMAVIQUE_CLOUDFLARE_ACCOUNT_ID", "abc123")
    settings = Settings(_env_file=None)
    assert settings.cloudflare_base_url == (
        "https://api.cloudflare.com/client/v4/accounts/abc123/ai/v1"
    )
