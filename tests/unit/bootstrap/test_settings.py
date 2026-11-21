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
