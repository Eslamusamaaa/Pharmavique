"""Find product pages through a shop's own sitemap instead of asking a search engine.

A sitemap is the list of page addresses a shop publishes for crawlers. We collect it once per shop
(politely, robots.txt first), keep the addresses in a JSON-lines file, and later find a drug's page
by matching the words of its name against the words in each address ("panadol-extra-24-tablets").
One request per sitemap file replaces one search per drug.
"""

import html
import json
import re
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote, urlparse

from pharmavique.media.application.page_search import SearchResultPage
from pharmavique.media.infrastructure.web import PoliteWeb
from pharmavique.shared_kernel.text import normalize_text

_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_MAX_DEPTH = 2  # an index of indexes is as deep as shops go
_QUERY_NOISE = frozenset({"saudi", "arabia", "السعوديه", "ksa"})


class SitemapCollector:
    def __init__(self, web: PoliteWeb, *, max_children: int = 500) -> None:
        self._web = web
        self._max_children = max_children

    async def collect(self, sitemap_url: str, out_path: Path) -> int:
        """Write every page address under `sitemap_url` to `out_path`; returns how many."""
        urls: dict[str, None] = {}
        await self._walk(sitemap_url, urls, depth=0)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as handle:
            for url in urls:
                handle.write(json.dumps({"url": url}, ensure_ascii=False) + "\n")
        return len(urls)

    async def _walk(self, url: str, found: dict[str, None], depth: int) -> None:
        response = await self._web.get(url)
        if response is None or response.status_code != 200:
            return
        locations = [html.unescape(loc) for loc in _LOC.findall(response.text)]
        if "<sitemapindex" in response.text[:2000].lower():
            if depth >= _MAX_DEPTH:
                return
            for child in locations[: self._max_children]:
                await self._walk(child, found, depth + 1)
            return
        for location in locations:
            found.setdefault(location, None)


def _address_tokens(url: str) -> frozenset[str]:
    return frozenset(normalize_text(unquote(urlparse(url).path)).split())


class SitemapPageSearch:
    """Implements `PageSearch` over sitemap files: every query word must be in the address."""

    def __init__(self, paths: Sequence[Path]) -> None:
        self._urls: list[str] = []
        self._sizes: list[int] = []
        self._postings: dict[str, list[int]] = {}
        seen: set[str] = set()
        for path in paths:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    url = json.loads(line)["url"]
                except (ValueError, KeyError):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                tokens = _address_tokens(url)
                index = len(self._urls)
                self._urls.append(url)
                self._sizes.append(len(tokens))
                for token in tokens:
                    self._postings.setdefault(token, []).append(index)

    async def search(self, query: str, limit: int) -> list[SearchResultPage]:
        words = [w for w in dict.fromkeys(normalize_text(query).split()) if w not in _QUERY_NOISE]
        if not words:
            return []
        lists = [self._postings.get(word) for word in words]
        if any(postings is None for postings in lists):
            return []
        ordered = sorted((p for p in lists if p is not None), key=len)
        matching = set(ordered[0])
        for postings in ordered[1:]:
            matching &= set(postings)
            if not matching:
                return []
        closest = sorted(matching, key=lambda i: (self._sizes[i] - len(words), self._urls[i]))
        return [SearchResultPage(self._urls[i], "") for i in closest[:limit]]
