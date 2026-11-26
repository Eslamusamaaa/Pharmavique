"""Per-client request limits: heavy endpoints (AI, voice, scan) have a lower one."""

from pathlib import Path

import httpx

from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.rate_limit import SlidingWindow
from pharmavique.bootstrap.web_app import mount_web_app


def test_a_window_allows_up_to_the_limit_then_refuses_until_the_oldest_request_expires() -> None:
    now = [0.0]
    window = SlidingWindow(limit=2, seconds=60.0, clock=lambda: now[0])

    assert window.allow("a") is True
    assert window.allow("a") is True
    assert window.allow("a") is False
    assert window.retry_after("a") == 60
    assert window.allow("b") is True  # another client has its own count

    now[0] = 61.0
    assert window.allow("a") is True


def test_idle_clients_are_forgotten_so_memory_does_not_grow() -> None:
    now = [0.0]
    window = SlidingWindow(limit=5, seconds=10.0, clock=lambda: now[0])
    for client in ("a", "b", "c"):
        window.allow(client)

    now[0] = 100.0
    window.allow("d")

    assert window.tracked() == 1


async def test_the_api_answers_429_with_retry_after_once_the_general_limit_is_used() -> None:
    app = create_app(rate_limit_per_minute=3, heavy_rate_limit_per_minute=0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        responses = [await api.get("/metrics") for _ in range(4)]
        health = await api.get("/health")

    assert [r.status_code for r in responses] == [200, 200, 200, 429]
    assert int(responses[3].headers["retry-after"]) >= 1
    assert health.status_code == 200  # health checks are never limited


async def test_heavy_endpoints_have_their_own_lower_limit() -> None:
    app = create_app(rate_limit_per_minute=100, heavy_rate_limit_per_minute=1)
    body = {"question": "x", "level": "patient"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        first = await api.post("/v1/assistant/ask", json=body)
        second = await api.post("/v1/assistant/ask", json=body)
        other = await api.get("/metrics")

    assert first.status_code != 429
    assert second.status_code == 429
    assert other.status_code == 200


async def test_a_limit_of_zero_turns_the_limiter_off() -> None:
    app = create_app(rate_limit_per_minute=0, heavy_rate_limit_per_minute=0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        statuses = {(await api.get("/health")).status_code for _ in range(10)}

    assert statuses == {200}


async def test_the_website_files_are_never_limited(tmp_path: Path) -> None:
    """Opening the site loads dozens of script, font and icon files; counting them made a phone
    (or several behind one carrier address) get 429 for a script and a broken screen."""
    (tmp_path / "_expo" / "static" / "js").mkdir(parents=True)
    (tmp_path / "_expo" / "static" / "js" / "[register]-abc.js").write_text("x")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "font.ttf").write_text("x")
    (tmp_path / "favicon.ico").write_text("x")
    (tmp_path / "index.html").write_text("<html></html>")
    app = create_app(rate_limit_per_minute=2, heavy_rate_limit_per_minute=0)
    mount_web_app(app, tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as api:
        files = [
            await api.get(path)
            for _ in range(5)
            for path in (
                "/_expo/static/js/%5Bregister%5D-abc.js",
                "/assets/font.ttf",
                "/favicon.ico",
            )
        ]
        calls = [await api.get("/metrics") for _ in range(3)]

    assert {r.status_code for r in files} == {200}
    assert [r.status_code for r in calls] == [200, 200, 429]  # the API is still limited
