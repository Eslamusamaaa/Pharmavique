"""Image search in two steps: a search gives pages, a page reader turns each into a candidate.

The search step is pluggable (`PageSearch`): a search API, or a results file filled by any search
runner. The reading step is the polite page reader. Together they implement the `ImageSearch` port
that the picture pipeline uses.
"""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from pharmavique.media.domain.matching import ImageCandidate

_NOT_PAGES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")


@dataclass(frozen=True, slots=True)
class SearchResultPage:
    url: str
    title: str


class PageSearch(Protocol):
    async def search(self, query: str, limit: int) -> list[SearchResultPage]: ...


class PageReader(Protocol):
    async def read(self, page_url: str) -> ImageCandidate | None: ...


class PageImageSearch:
    """Implements `ImageSearch` over a `PageSearch` and a `PageReader`."""

    def __init__(self, search: PageSearch, reader: PageReader) -> None:
        self._search = search
        self._reader = reader

    async def search(self, query: str, limit: int) -> list[ImageCandidate]:
        seen: set[str] = set()
        candidates: list[ImageCandidate] = []
        for result in await self._search.search(query, limit):
            if result.url in seen or urlparse(result.url).path.lower().endswith(_NOT_PAGES):
                continue
            seen.add(result.url)
            candidate = await self._reader.read(result.url)
            if candidate is not None:
                candidates.append(candidate)
        return candidates
