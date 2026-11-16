"""Runs a real headless Chromium against a throwaway local server (needs `playwright install`)."""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from pharmavique.foundation.http.throttle import Throttle
from pharmavique.ingestion.infrastructure.connectors.sfda_web.playwright_fetcher import (
    PlaywrightPageFetcher,
)

pytestmark = pytest.mark.integration

PAGE = b"""<html><head><link rel="stylesheet" href="/style.css"></head>
<body><img src="/pic.png">
<table><tr><th>Register Number</th><td>42</td></tr></table></body></html>"""


class Recorder(BaseHTTPRequestHandler):
    seen: ClassVar[list[tuple[str, str]]] = []  # (path, user agent)

    def do_GET(self) -> None:
        Recorder.seen.append((self.path, self.headers.get("User-Agent", "")))
        if self.path == "/page":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return None


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def server() -> Iterator[str]:
    Recorder.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


async def test_fetches_html_sends_user_agent_and_skips_heavy_resources(server: str) -> None:
    async with PlaywrightPageFetcher(
        user_agent="TestAgent/1.0", throttle=Throttle(0.0), clock=FixedClock()
    ) as fetcher:
        page = await fetcher.fetch(f"{server}/page")
        missing = await fetcher.fetch(f"{server}/nope")

    assert page.status == 200
    assert "<td>42</td>" in page.html
    assert missing.status == 404
    requested = [path for path, _ in Recorder.seen]
    assert "/page" in requested
    assert "/pic.png" not in requested
    assert "/style.css" not in requested
    assert all(agent == "TestAgent/1.0" for path, agent in Recorder.seen if path == "/page")
