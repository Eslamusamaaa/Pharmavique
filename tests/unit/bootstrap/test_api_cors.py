"""The API lets the app's web build call it from the origins in settings, and no others."""

import httpx

from pharmavique.bootstrap.api import create_app


async def preflight(origins: list[str], origin: str) -> httpx.Response:
    app = create_app(cors_origins=origins)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.options(
            "/health",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )


async def test_an_allowed_origin_gets_the_cors_header() -> None:
    response = await preflight(["http://localhost:8081"], "http://localhost:8081")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8081"


async def test_an_unknown_origin_gets_no_cors_header() -> None:
    response = await preflight(["http://localhost:8081"], "http://evil.example")

    assert "access-control-allow-origin" not in response.headers


async def test_no_origins_means_no_cors_middleware() -> None:
    response = await preflight([], "http://localhost:8081")

    assert "access-control-allow-origin" not in response.headers
