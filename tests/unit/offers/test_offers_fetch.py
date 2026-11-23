"""Polite fetching and sitemap reading, against a fake server (httpx MockTransport)."""

import dataclasses
import gzip

import httpx
import pytest

from pharmavique.foundation.http.robots import RobotsPolicy
from pharmavique.offers.application.ports import FetchFailed, FetchResult, SourceBlocked
from pharmavique.offers.infrastructure.config import RetailerConfig
from pharmavique.offers.infrastructure.fetch import USER_AGENT, PoliteFetcher
from pharmavique.offers.infrastructure.sitemap import SitemapReader, parse_sitemap

CONFIG = RetailerConfig(
    id="t",
    name="T",
    base_url="https://shop.test",
    platform="jsonld",
    language="en",
    market="SA",
    sitemaps=("https://shop.test/sitemap.xml",),
    min_interval=2.0,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def fetcher(handler, clock: Clock, policy: RobotsPolicy | None = None, **options):
    return PoliteFetcher(
        client(handler), policy, 2.0, sleep=clock.sleep, clock=clock.time, **options
    )


async def test_requests_are_spaced_by_the_interval() -> None:
    clock = Clock()
    f = fetcher(lambda r: httpx.Response(200, content=b"ok"), clock)

    await f.get("https://shop.test/a")
    await f.get("https://shop.test/b")

    assert clock.slept == [2.0]


async def test_a_url_robots_txt_forbids_is_never_requested() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200)

    policy = RobotsPolicy.from_text("User-agent: *\nDisallow: /*?", USER_AGENT)
    f = fetcher(handler, Clock(), policy)

    with pytest.raises(SourceBlocked):
        await f.get("https://shop.test/p?x=1")
    assert asked == []


@pytest.mark.parametrize("status", [401, 403, 429])
async def test_a_block_ends_it_at_once_without_a_retry(status: int) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status)

    f = fetcher(handler, Clock())

    with pytest.raises(SourceBlocked):
        await f.get("https://shop.test/a")
    assert len(calls) == 1


async def test_a_server_error_is_retried_then_succeeds() -> None:
    answers = iter([503, 200])
    clock = Clock()
    f = fetcher(lambda r: httpx.Response(next(answers), content=b"ok"), clock, retry_wait=7.0)

    result = await f.get("https://shop.test/a")

    assert result.status == 200
    assert 7.0 in clock.slept


async def test_a_page_that_keeps_failing_is_a_failed_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    f = fetcher(handler, Clock(), retries=3)

    with pytest.raises(FetchFailed):
        await f.get("https://shop.test/a")


async def test_a_missing_page_is_a_normal_answer_not_an_error() -> None:
    f = fetcher(lambda r: httpx.Response(404), Clock())

    assert (await f.get("https://shop.test/gone")).status == 404


async def test_the_sites_crawl_delay_raises_the_interval() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nCrawl-delay: 5\nDisallow: /admin")

    built = await PoliteFetcher.for_retailer(CONFIG, client(handler))

    assert built.interval == 5.0


async def test_a_site_without_robots_txt_is_allowed_and_a_failing_one_stops() -> None:
    missing = await PoliteFetcher.for_retailer(CONFIG, client(lambda r: httpx.Response(404)))
    assert missing.interval == 2.0
    with pytest.raises(SourceBlocked):
        await PoliteFetcher.for_retailer(CONFIG, client(lambda r: httpx.Response(403)))


INDEX = """<?xml version="1.0"?><sitemapindex xmlns="x">
<sitemap><loc>https://shop.test/products-1.xml</loc></sitemap>
<sitemap><loc>https://shop.test/blog.xml</loc></sitemap></sitemapindex>"""
PRODUCTS = """<urlset xmlns="x">
<url><loc>https://shop.test/p/1</loc><lastmod>2026-11-22</lastmod></url>
<url><loc>https://shop.test/p/2?a=1&amp;b=2</loc></url>
<url><loc>https://shop.test/cat/x</loc></url></urlset>"""


class MapFetcher:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.asked: list[str] = []

    async def get(self, url: str) -> FetchResult:
        self.asked.append(url)
        return FetchResult(200, self.files[url])


def test_a_sitemap_file_gives_addresses_dates_and_unescaped_links() -> None:
    is_index, entries = parse_sitemap(PRODUCTS)

    assert not is_index
    assert [(e.url, e.lastmod) for e in entries] == [
        ("https://shop.test/p/1", "2026-11-22"),
        ("https://shop.test/p/2?a=1&b=2", None),
        ("https://shop.test/cat/x", None),
    ]
    assert parse_sitemap(INDEX)[0] is True


async def test_an_index_is_followed_only_into_the_wanted_children_and_addresses_are_filtered() -> (
    None
):
    config = dataclasses.replace(CONFIG, sitemap_include="products", url_include="/p/[0-9]+$")
    files = {
        "https://shop.test/sitemap.xml": INDEX.encode(),
        "https://shop.test/products-1.xml": gzip.compress(PRODUCTS.encode()),
    }
    source = MapFetcher(files)

    entries = await SitemapReader(config, source).entries()

    assert [e.url for e in entries] == ["https://shop.test/p/1"]
    assert "https://shop.test/blog.xml" not in source.asked


async def test_a_sitemap_that_does_not_answer_is_an_error_not_an_empty_list() -> None:
    class Down:
        async def get(self, url: str) -> FetchResult:
            return FetchResult(500, b"")

    with pytest.raises(FetchFailed):
        await SitemapReader(CONFIG, Down()).entries()
