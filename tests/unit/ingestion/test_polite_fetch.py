from datetime import UTC, datetime

import pytest

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.connectors.sfda_web.errors import (
    FetchFailed,
    NotFound,
    SourceBlocked,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import ParseError
from pharmavique.ingestion.infrastructure.connectors.sfda_web.polite_fetch import PoliteFetch

URL = "https://example.test/list?page=1"
ROBOTS = RobotsPolicy.from_text("User-agent: *\nDisallow: /private\n", "test-agent")


class ScriptedFetcher:
    """Answers each call from a script: a status code and html, or an exception to raise."""

    def __init__(self, *script: tuple[int, str] | Exception) -> None:
        self.script = list(script)
        self.calls = 0

    async def fetch(self, url: str) -> FetchedPage:
        self.calls += 1
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        status, html = step
        return FetchedPage(url, status, html, datetime(2026, 1, 1, tzinfo=UTC))


class Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def parse_ok(html: str) -> str:
    if html != "good":
        raise ParseError("not a list page")
    return html.upper()


def polite(fetcher: ScriptedFetcher, sleeps: Sleeps, retries: int = 3) -> PoliteFetch:
    return PoliteFetch(fetcher, ROBOTS, retries=retries, retry_wait=10.0, sleep=sleeps)


async def test_returns_the_page_and_what_the_parser_made_of_it() -> None:
    fetcher = ScriptedFetcher((200, "good"))

    page, parsed = await polite(fetcher, Sleeps()).fetch_valid(URL, parse_ok)

    assert (page.status, parsed, fetcher.calls) == (200, "GOOD", 1)


async def test_a_url_robots_forbids_is_never_requested() -> None:
    fetcher = ScriptedFetcher((200, "good"))

    with pytest.raises(SourceBlocked):
        await polite(fetcher, Sleeps()).fetch_valid("https://example.test/private/x", parse_ok)

    assert fetcher.calls == 0


@pytest.mark.parametrize("status", [401, 403, 429])
async def test_a_block_status_stops_at_once_without_retrying(status: int) -> None:
    fetcher = ScriptedFetcher((status, ""))
    sleeps = Sleeps()

    with pytest.raises(SourceBlocked):
        await polite(fetcher, sleeps).fetch_valid(URL, parse_ok)

    assert (fetcher.calls, sleeps.waits) == (1, [])


async def test_a_404_is_reported_as_not_found_without_retrying() -> None:
    fetcher = ScriptedFetcher((404, ""))

    with pytest.raises(NotFound):
        await polite(fetcher, Sleeps()).fetch_valid(URL, parse_ok)

    assert fetcher.calls == 1


async def test_network_errors_and_server_errors_are_retried_with_a_growing_wait() -> None:
    fetcher = ScriptedFetcher(ConnectionResetError("reset"), (503, ""), (200, "good"))
    sleeps = Sleeps()

    _, parsed = await polite(fetcher, sleeps).fetch_valid(URL, parse_ok)

    assert parsed == "GOOD"
    assert sleeps.waits == [10.0, 20.0]


async def test_a_page_that_never_parses_is_never_returned() -> None:
    fetcher = ScriptedFetcher((200, "<html>captcha</html>"))

    with pytest.raises(FetchFailed, match="not a list page"):
        await polite(fetcher, Sleeps()).fetch_valid(URL, parse_ok)

    assert fetcher.calls == 3


async def test_it_gives_up_after_the_allowed_attempts() -> None:
    fetcher = ScriptedFetcher(TimeoutError("slow"))
    sleeps = Sleeps()

    with pytest.raises(FetchFailed):
        await polite(fetcher, sleeps, retries=2).fetch_valid(URL, parse_ok)

    assert (fetcher.calls, sleeps.waits) == (2, [10.0])
