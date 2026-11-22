"""Polite web access for pictures: read a product page, download its image.

The rules, the same ones the SFDA crawler keeps:
- robots.txt of the site is read first and obeyed; a page it forbids is never requested;
- one throttle **per host**, so many sites can be worked in parallel without pressing on any one;
- a site that answers 401 or 403, or shows a bot check ("Just a moment...", a CAPTCHA), is
  marked blocked for the rest of the run and not asked again. Nothing here works around a block;
- a site that answers 429 ("slow down") is left alone for the time it asks (Retry-After) or a few
  minutes, longer each time, and only given up for the run after repeated 429s. While a site
  cools down nothing is requested from it, so `incidents` counts those missed requests and the
  caller can try the drug again later instead of recording "no picture";
- a download is accepted only if the bytes really are an image of a sensible size, whatever the
  server claims about the content type.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.foundation.http.throttle import Throttle
from pharmavique.media.application.ports import DownloadedImage
from pharmavique.media.domain.matching import ImageCandidate

_log = logging.getLogger("media.web")
_BLOCK_STATUSES = (401, 403)
_COOLDOWN_SECONDS = 120.0  # first 429 without Retry-After; doubles with every strike
_MAX_COOLDOWN = 1800.0
_STRIKES_BEFORE_GIVING_UP = 5
_REFUSALS_BEFORE_BLOCKING = 5  # picture files refused in a row before the host counts as blocking
_BLOCK_MARKERS = ("just a moment", "attention required", "access denied", "captcha")
_MAX_PAGE_TEXT = 1_500
_MAX_IMAGE_BYTES = 5_000_000
_MIN_IMAGE_BYTES = 1_000
_MAGIC = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"GIF8": "image/gif"}


def _sniff(data: bytes) -> str | None:
    """The image type the bytes themselves show, not the one the server claims."""
    for magic, content_type in _MAGIC.items():
        if data.startswith(magic):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class PoliteWeb:
    def __init__(
        self,
        client: httpx.AsyncClient,
        throttle_factory: Callable[[], Throttle],
        *,
        user_agent: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._cool_until: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self.incidents = 0  # requests not made because a site was blocked or cooling down
        self._client = client
        self._throttle_factory = throttle_factory
        self._throttles: dict[str, tuple[Throttle, asyncio.Lock]] = {}
        self._user_agent = user_agent
        self._robots: dict[str, RobotsPolicy | None] = {}
        self._unreadable: set[str] = set()
        self._refused: dict[str, int] = {}  # picture files refused (401/403) in a row, per host
        self.blocked_hosts: set[str] = set()

    async def get(self, url: str, *, strict_robots: bool = True) -> httpx.Response | None:
        """The response, or None when the site is blocked, forbids the URL, or the request fails.

        A page host whose robots.txt cannot be read is treated as blocked. For image files
        (`strict_robots=False`) an unreadable robots.txt means "no rules": CDN buckets often
        refuse robots.txt while serving files normally. A readable robots.txt is always obeyed,
        and a refusal of the file itself still marks the host blocked.
        """
        host = urlparse(url).netloc
        if host in self.blocked_hosts or self._cooling(host):
            self.incidents += 1
            return None
        policy = await self._policy_for(url, strict=strict_robots)
        if policy is None:
            self.incidents += 1
            return None
        if not policy.allows(url):
            return None
        response = await self._request(url)
        if response is None:
            return None
        if response.status_code == 429:
            self._cool(host, response.headers.get("retry-after"))
            self.incidents += 1
            return None
        if self._is_block(response):
            if not strict_robots and response.status_code in _BLOCK_STATUSES:
                # A picture file that answers 403 is often one that was removed while the host
                # serves the others; only a run of refusals means the host is blocking us.
                self._refused[host] = self._refused.get(host, 0) + 1
                if self._refused[host] < _REFUSALS_BEFORE_BLOCKING:
                    self.incidents += 1
                    return None
            self._block(host, f"HTTP {response.status_code} or a bot check at {url}")
            self.incidents += 1
            return None
        self._refused.pop(host, None)
        return response

    async def _policy_for(self, url: str, *, strict: bool) -> RobotsPolicy | None:
        parts = urlparse(url)
        host = parts.netloc
        if host not in self._robots:
            response = await self._request(f"{parts.scheme}://{host}/robots.txt")
            if response is not None and response.status_code == 200:
                self._robots[host] = RobotsPolicy.from_text(response.text, self._user_agent)
            elif response is not None and response.status_code == 404:
                self._robots[host] = RobotsPolicy.from_text("", self._user_agent)
            elif response is not None and response.status_code in _BLOCK_STATUSES:
                self._robots[host] = None
                self._unreadable.add(host)
            else:  # a network error, a 429 or a server error: ask again later, do not give up
                if response is not None and response.status_code == 429:
                    self._cool(host, response.headers.get("retry-after"))
                else:
                    self._cool(host, None, strike=False)
                return None
        policy = self._robots[host]
        if policy is None and host in self._unreadable:
            if strict:
                self._block(host, "robots.txt could not be read")
                return None
            return RobotsPolicy.from_text("", self._user_agent)
        return policy

    async def _request(self, url: str) -> httpx.Response | None:
        host = urlparse(url).netloc
        if host not in self._throttles:
            self._throttles[host] = (self._throttle_factory(), asyncio.Lock())
        throttle, lock = self._throttles[host]
        async with lock:  # requests to one host queue up behind its throttle
            await throttle.wait()
        try:
            return await self._client.get(
                url, headers={"User-Agent": self._user_agent}, follow_redirects=True
            )
        except httpx.HTTPError as error:
            _log.warning("request failed for %s: %s", url, error)
            return None

    @staticmethod
    def _is_block(response: httpx.Response) -> bool:
        if response.status_code in _BLOCK_STATUSES:
            return True
        content_type = response.headers.get("content-type", "")
        if response.status_code == 200 and content_type.startswith("text/html"):
            return any(marker in response.text[:3000].lower() for marker in _BLOCK_MARKERS)
        return False

    def _cooling(self, host: str) -> bool:
        return self._clock() < self._cool_until.get(host, 0.0)

    def _cool(self, host: str, retry_after: str | None, *, strike: bool = True) -> None:
        """Leave a site alone for a while; give it up for the run after repeated strikes."""
        if strike:
            self._strikes[host] = self._strikes.get(host, 0) + 1
        strikes = self._strikes.get(host, 0)
        if strikes >= _STRIKES_BEFORE_GIVING_UP:
            self._block(host, f"{strikes} rate-limit answers in a row")
            return
        if retry_after and retry_after.strip().isdigit():
            wait = float(retry_after)  # the site said how long it needs
        elif strike:
            wait = _COOLDOWN_SECONDS * (2 ** (strikes - 1))
        else:
            wait = _COOLDOWN_SECONDS / 2  # robots.txt could not be read: try again soon
        wait = min(wait, _MAX_COOLDOWN)
        self._cool_until[host] = self._clock() + wait
        _log.warning(
            "leaving %s alone for %.0f s (rate limit or unreadable robots.txt)", host, wait
        )

    def _block(self, host: str, reason: str) -> None:
        _log.warning("not asking %s again this run: %s", host, reason)
        self.blocked_hosts.add(host)


class WebPageReader:
    """Reads a product page into an `ImageCandidate`: its picture, title, headings and text."""

    def __init__(self, web: PoliteWeb) -> None:
        self._web = web
        self._seen: dict[str, ImageCandidate | None] = {}  # a page is requested once per run

    async def read(self, page_url: str) -> ImageCandidate | None:
        if page_url not in self._seen:
            self._seen[page_url] = await self._read_page(page_url)
        return self._seen[page_url]

    async def _read_page(self, page_url: str) -> ImageCandidate | None:
        response = await self._web.get(page_url)
        if response is None or response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        image = soup.find("meta", property="og:image")
        content = image.get("content") if image else None
        if not content:
            return None

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = " ".join(
            part
            for part in (
                soup.title.get_text(" ", strip=True) if soup.title else "",
                _meta(soup, "property", "og:title"),
            )
            if part
        )
        heading = soup.find("h1")
        description = _meta(soup, "name", "description")
        body = " ".join(soup.get_text(" ", strip=True).split())
        return ImageCandidate(
            image_url=urljoin(page_url, str(content)),
            page_url=page_url,
            title=title,
            alt_text=heading.get_text(" ", strip=True) if heading else "",
            page_text=f"{description} {body}"[:_MAX_PAGE_TEXT].strip(),
        )


def _meta(soup: BeautifulSoup, attribute: str, value: str) -> str:
    tag = soup.find("meta", attrs={attribute: value})
    return str(tag.get("content", "")).strip() if tag else ""


class HttpImageDownloader:
    """Implements the `ImageDownloader` port over `PoliteWeb`."""

    def __init__(self, web: PoliteWeb) -> None:
        self._web = web

    async def download(self, url: str) -> DownloadedImage | None:
        response = await self._web.get(url, strict_robots=False)
        if response is None or response.status_code != 200:
            return None
        data = response.content
        content_type = _sniff(data)
        if content_type is None or not _MIN_IMAGE_BYTES <= len(data) <= _MAX_IMAGE_BYTES:
            return None
        return DownloadedImage(data=data, content_type=content_type)
