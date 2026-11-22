"""The database address as Neon or Vercel hands it out becomes one the async driver accepts."""

import pytest

from pharmavique.bootstrap.settings import Settings
from pharmavique.foundation.db.url import to_asyncpg_url

NEON = "postgresql://user:p%40ss@ep-cool-123-pooler.eu-central-1.aws.neon.tech/neondb"


def test_a_plain_postgres_address_gets_the_async_driver() -> None:
    assert to_asyncpg_url("postgresql://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
    assert to_asyncpg_url("postgres://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"


def test_an_address_that_already_names_the_async_driver_is_left_alone() -> None:
    url = "postgresql+asyncpg://u:p@localhost:5432/pharmavique"
    assert to_asyncpg_url(url) == url


def test_sslmode_becomes_the_ssl_option_asyncpg_understands() -> None:
    assert (
        to_asyncpg_url(f"{NEON}?sslmode=require")
        == "postgresql+asyncpg://user:p%40ss@ep-cool-123-pooler.eu-central-1.aws.neon.tech/neondb"
        "?ssl=require"
    )


def test_channel_binding_is_dropped_because_asyncpg_rejects_it() -> None:
    converted = to_asyncpg_url(f"{NEON}?sslmode=require&channel_binding=require")
    assert "channel_binding" not in converted
    assert converted.endswith("?ssl=require")


def test_other_options_are_kept() -> None:
    converted = to_asyncpg_url(f"{NEON}?sslmode=require&application_name=pv")
    assert "application_name=pv" in converted
    assert "ssl=require" in converted


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "verify-ca", "verify-full"])
def test_every_sslmode_maps_to_the_same_value_for_ssl(mode: str) -> None:
    assert to_asyncpg_url(f"postgresql://u:p@h/d?sslmode={mode}").endswith(f"?ssl={mode}")


def test_the_setting_converts_what_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PHARMAVIQUE_DATABASE_URL", f"{NEON}?sslmode=require&channel_binding=require"
    )
    settings = Settings(_env_file=None)
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")
    assert settings.database_url.get_secret_value().endswith("?ssl=require")
