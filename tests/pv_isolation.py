"""A pytest plugin (loaded with `-p pv_isolation`): tests do not depend on the developer's `.env`.

A set variable beats the `.env` file, so these empty ones switch off what the real file may enable
and a test never meant to see: the website the API serves at `/` would answer addresses that the
API tests expect to be unknown.

It also holds fixtures every test folder may use.
"""

import os
from collections.abc import Iterator

import pytest

from pharmavique.bootstrap.features import get_features

os.environ["PHARMAVIQUE_WEB_DIR"] = ""


@pytest.fixture
def ai_open_to_guests(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Switch off `login_for_ai` for tests about what a model route does, not who may call it
    (that is `tests/unit/bootstrap/test_api_login_required.py`)."""
    monkeypatch.setenv("PHARMAVIQUE_FEATURE_LOGIN_FOR_AI", "false")
    get_features.cache_clear()
    yield
    get_features.cache_clear()
