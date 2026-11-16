from collections.abc import AsyncIterator

import httpx
import pytest

from pharmavique.bootstrap.api import create_app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_returns_ok_without_secrets(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "pharmavique"
    assert set(body) == {"status", "service", "version", "environment"}


async def test_openapi_documents_health_endpoint(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    assert "/health" in schema["paths"]
