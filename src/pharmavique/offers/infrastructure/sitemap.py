"""Read a retailer's sitemaps: the product addresses and the date each was last changed.

Follows sitemap indexes (two levels at most), reads `.gz` files, keeps only the addresses the
retailer's configuration allows. Every file is fetched through the polite fetcher.
"""

import gzip
import html
import re

from pharmavique.offers.application.ports import FetchFailed, PageFetcher, SitemapEntry
from pharmavique.offers.infrastructure.config import RetailerConfig

__all__ = ["SitemapReader", "parse_sitemap"]

_BLOCK = re.compile(r"<(url|sitemap)>(.*?)</\1>", re.S | re.I)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S | re.I)
_LASTMOD = re.compile(r"<lastmod>\s*(.*?)\s*</lastmod>", re.S | re.I)
MAX_DEPTH = 2


def parse_sitemap(text: str) -> tuple[bool, list[SitemapEntry]]:
    """(is an index, the entries) of one sitemap file."""
    is_index = "<sitemapindex" in text.lower()
    entries = []
    for _, body in _BLOCK.findall(text):
        loc = _LOC.search(body)
        if loc is None:
            continue
        lastmod = _LASTMOD.search(body)
        entries.append(
            SitemapEntry(html.unescape(loc.group(1)), lastmod.group(1) if lastmod else None)
        )
    return is_index, entries


def _text(content: bytes) -> str:
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    return content.decode("utf-8", errors="replace")


class SitemapReader:
    def __init__(self, config: RetailerConfig, fetcher: PageFetcher) -> None:
        self._config = config
        self._fetcher = fetcher

    def _wanted(self, url: str) -> bool:
        include, exclude = self._config.url_include, self._config.url_exclude
        if include and not re.search(include, url):
            return False
        return not (exclude and re.search(exclude, url))

    async def entries(self) -> list[SitemapEntry]:
        found: dict[str, SitemapEntry] = {}
        seen: set[str] = set()
        queue = [(url, 0) for url in self._config.sitemaps]
        while queue:
            url, depth = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            result = await self._fetcher.get(url)
            if result.status != 200:
                raise FetchFailed(f"sitemap {url} answered {result.status}")
            is_index, entries = parse_sitemap(_text(result.content))
            if is_index:
                if depth >= MAX_DEPTH:
                    continue
                pattern = self._config.sitemap_include
                queue += [
                    (e.url, depth + 1) for e in entries if not pattern or re.search(pattern, e.url)
                ]
                continue
            for entry in entries:
                if self._wanted(entry.url):
                    found.setdefault(entry.url, entry)
        return list(found.values())
