"""/ready says whether this instance can serve traffic: the database answers and, when set, the
shared store answers. It never shows connection details or error text."""

import asyncio

import httpx
import pytest

from pharmavique.bootstrap import health
from pharmavique.bootstrap.api import create_app
from pharmavique.foundation.kv import MemoryStore, StoreUnavailable


async def _ok() -> None:
    return None


async def _broken() -> None:
    raise ConnectionError("postgresql://user:secret@db.internal:5432 refused")


async def _hangs() -> None:
    await asyncio.sleep(10)


class _DownStore(MemoryStore):
    async def get(self, key: str) -> bytes | None:
        raise StoreUnavailable("redis://secret@cache.internal timed out")


async def _get(app: object, path: str = "/ready") -> httpx.Response:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(path)


@pytest.fixture(autouse=True)
def _short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.05)


async def test_ready_when_database_answers_and_no_store_is_set() -> None:
    app = create_app()
    app.state.database_ping = _ok

    response = await _get(app)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "shared_store": "not_configured"},
    }


async def test_ready_checks_the_shared_store_when_one_is_set() -> None:
    app = create_app(store=MemoryStore())
    app.state.database_ping = _ok

    body = (await _get(app)).json()

    assert body["checks"]["shared_store"] == "ok"


async def test_not_ready_when_database_fails_and_no_details_leak() -> None:
    app = create_app()
    app.state.database_ping = _broken

    response = await _get(app)

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "failed"
    assert "secret" not in response.text
    assert "db.internal" not in response.text


async def test_not_ready_when_database_does_not_answer_in_time() -> None:
    app = create_app()
    app.state.database_ping = _hangs

    response = await _get(app)

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "failed"


async def test_not_ready_when_the_shared_store_is_down() -> None:
    app = create_app(store=_DownStore())
    app.state.database_ping = _ok

    response = await _get(app)

    assert response.status_code == 503
    assert response.json()["checks"]["shared_store"] == "failed"
    assert "secret" not in response.text


async def test_without_a_database_dev_is_ready_and_prod_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pharmavique.bootstrap.settings import get_settings

    dev = await _get(create_app())
    assert dev.status_code == 200
    assert dev.json()["checks"]["database"] == "not_configured"

    monkeypatch.setenv("PHARMAVIQUE_ENVIRONMENT", "prod")
    monkeypatch.setenv("PHARMAVIQUE_JWT_SECRET", "x" * 40)
    get_settings.cache_clear()
    try:
        prod = await _get(create_app())
    finally:
        get_settings.cache_clear()
    assert prod.status_code == 503
    assert prod.json()["checks"]["database"] == "not_configured"


async def test_ready_is_in_the_openapi_schema() -> None:
    schema = (await _get(create_app(), "/openapi.json")).json()

    assert "/ready" in schema["paths"]
