"""Fetch pages with a headless Chromium (Playwright), politely.

Politeness choices: one page at a time, every request goes through the throttle, images, fonts,
media and stylesheets are never downloaded (the data is in the HTML), and JavaScript is off by
default because the SFDA pages are rendered on the server.
"""

from types import TracebackType
from typing import Self

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Route,
    async_playwright,
)

from pharmavique.foundation.http.throttle import Throttle
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.shared_kernel.ports import Clock

_SKIPPED_RESOURCES = frozenset({"image", "font", "media", "stylesheet"})


async def _skip_heavy_resources(route: Route) -> None:
    if route.request.resource_type in _SKIPPED_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


class PlaywrightPageFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        throttle: Throttle,
        clock: Clock,
        timeout_ms: int = 45_000,
        java_script: bool = False,
        headless: bool = True,
    ) -> None:
        self._user_agent = user_agent
        self._throttle = throttle
        self._clock = clock
        self._timeout_ms = timeout_ms
        self._java_script = java_script
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> Self:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            user_agent=self._user_agent,
            java_script_enabled=self._java_script,
            locale="en-US",
        )
        await self._context.route("**/*", _skip_heavy_resources)
        self._page = await self._context.new_page()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def fetch(self, url: str) -> FetchedPage:
        if self._page is None:
            raise RuntimeError("use the fetcher as an async context manager")
        await self._throttle.wait()
        response = await self._page.goto(
            url, wait_until="domcontentloaded", timeout=self._timeout_ms
        )
        html = await self._page.content()
        return FetchedPage(
            url=url,
            status=response.status if response is not None else 0,
            html=html,
            fetched_at=self._clock.now(),
        )
