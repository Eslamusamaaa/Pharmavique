"""Sitemaps: collect a shop's page addresses once, then find product pages by their names."""

import json
from pathlib import Path

import httpx

from pharmavique.foundation.http.throttle import Throttle
from pharmavique.media.infrastructure.sitemaps import SitemapCollector, SitemapPageSearch
from pharmavique.media.infrastructure.web import PoliteWeb


def urlset(*urls: str) -> bytes:
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'.encode()


def index(*urls: str) -> bytes:
    body = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in urls)
    return f'<?xml version="1.0"?><sitemapindex xmlns="x">{body}</sitemapindex>'.encode()


class Site:
    def __init__(self, routes: dict[str, bytes], robots: bytes = b"") -> None:
        self.routes = routes
        self.robots = robots
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = request.url.path + (f"?{request.url.query.decode()}" if request.url.query else "")
        self.requests.append(key)
        if request.url.path == "/robots.txt":
            return httpx.Response(200 if self.robots else 404, content=self.robots)
        body = self.routes.get(key)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "application/xml"}, content=body)


def collector(site: Site) -> SitemapCollector:
    client = httpx.AsyncClient(transport=httpx.MockTransport(site))
    return SitemapCollector(PoliteWeb(client, lambda: Throttle(0.0), user_agent="test"))


async def test_an_index_is_followed_to_its_child_sitemaps_and_urls_are_kept_once(
    tmp_path: Path,
) -> None:
    site = Site(
        {
            "/sitemap.xml": index(
                "https://shop.example.sa/s1.xml", "https://shop.example.sa/s2.xml?from=1&amp;to=2"
            ),
            "/s1.xml": urlset(
                "https://shop.example.sa/p/panadol-extra", "https://shop.example.sa/p/a"
            ),
            "/s2.xml?from=1&to=2": urlset(
                "https://shop.example.sa/p/a", "https://shop.example.sa/p/b"
            ),
        }
    )
    out = tmp_path / "shop.jsonl"

    count = await collector(site).collect("https://shop.example.sa/sitemap.xml", out)

    urls = [json.loads(line)["url"] for line in out.read_text(encoding="utf-8").splitlines()]
    assert count == 3
    assert urls == [
        "https://shop.example.sa/p/panadol-extra",
        "https://shop.example.sa/p/a",
        "https://shop.example.sa/p/b",
    ]


async def test_a_missing_child_sitemap_does_not_stop_the_rest(tmp_path: Path) -> None:
    site = Site(
        {
            "/sitemap.xml": index(
                "https://shop.example.sa/gone.xml", "https://shop.example.sa/s2.xml"
            ),
            "/s2.xml": urlset("https://shop.example.sa/p/a"),
        }
    )

    count = await collector(site).collect(
        "https://shop.example.sa/sitemap.xml", tmp_path / "o.jsonl"
    )

    assert count == 1


async def test_a_sitemap_robots_txt_forbids_is_not_requested(tmp_path: Path) -> None:
    site = Site(
        {"/sitemap.xml": urlset("https://shop.example.sa/p/a")},
        robots=b"User-agent: *\nDisallow: /sitemap.xml\n",
    )

    count = await collector(site).collect(
        "https://shop.example.sa/sitemap.xml", tmp_path / "o.jsonl"
    )

    assert count == 0
    assert "/sitemap.xml" not in site.requests


def write_urls(path: Path, *urls: str) -> None:
    path.write_text("\n".join(json.dumps({"url": u}) for u in urls), encoding="utf-8")


async def test_search_finds_pages_whose_address_has_every_word_of_the_query(tmp_path: Path) -> None:
    path = tmp_path / "shop.jsonl"
    write_urls(
        path,
        "https://shop.example.sa/en/panadol-extra-24-tablets.html",
        "https://shop.example.sa/en/panadol-advance-96-tablets.html",
        "https://shop.example.sa/en/augmentin-375mg-tab",
    )
    search = SitemapPageSearch([path])

    found = await search.search("PANADOL EXTRA Saudi Arabia", 5)

    assert [p.url for p in found] == ["https://shop.example.sa/en/panadol-extra-24-tablets.html"]


async def test_the_closest_address_comes_first_and_the_limit_applies(tmp_path: Path) -> None:
    path = tmp_path / "shop.jsonl"
    write_urls(
        path,
        "https://shop.example.sa/en/brufen-400mg-30-tablets-large-family-pack-promo",
        "https://shop.example.sa/en/brufen-400mg-30-tablets",
        "https://shop.example.sa/en/brufen-syrup",
    )
    search = SitemapPageSearch([path])

    found = await search.search("BRUFEN 400 mg", 1)

    assert [p.url for p in found] == ["https://shop.example.sa/en/brufen-400mg-30-tablets"]


async def test_arabic_names_match_arabic_addresses_and_percent_encoding_is_understood(
    tmp_path: Path,
) -> None:
    path = tmp_path / "shop.jsonl"
    write_urls(
        path,
        "https://shop.example.sa/ar/%D8%A8%D8%A7%D9%86%D8%A7%D8%AF%D9%88%D9%84-%D8%A7%D9%83%D8%B3%D8%AA%D8%B1%D8%A7",
    )
    search = SitemapPageSearch([path])

    found = await search.search("بَانَادُول اكسترا السعودية", 5)

    assert len(found) == 1


async def test_a_query_of_only_noise_finds_nothing(tmp_path: Path) -> None:
    path = tmp_path / "shop.jsonl"
    write_urls(path, "https://shop.example.sa/en/anything")

    assert await SitemapPageSearch([path]).search("Saudi Arabia", 5) == []
