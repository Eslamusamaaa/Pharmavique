"""Search is two steps: a search gives pages, a page reader turns each page into a candidate."""

import json
from pathlib import Path

from pharmavique.media.application.page_search import PageImageSearch, SearchResultPage
from pharmavique.media.domain.matching import ImageCandidate
from pharmavique.media.infrastructure.search_file import FilePageSearch


class FakePageSearch:
    def __init__(self, pages: dict[str, list[SearchResultPage]]) -> None:
        self.pages = pages

    async def search(self, query: str, limit: int) -> list[SearchResultPage]:
        return self.pages.get(query, [])[:limit]


class FakeReader:
    def __init__(self, known: dict[str, ImageCandidate]) -> None:
        self.known = known
        self.read_urls: list[str] = []

    async def read(self, page_url: str) -> ImageCandidate | None:
        self.read_urls.append(page_url)
        return self.known.get(page_url)


def candidate(url: str, title: str = "t") -> ImageCandidate:
    return ImageCandidate(image_url=f"{url}/i.jpg", page_url=url, title=title, alt_text="")


async def test_each_result_page_is_read_and_only_readable_ones_become_candidates() -> None:
    search = FakePageSearch(
        {
            "q": [
                SearchResultPage("https://a.example.sa/p", "A"),
                SearchResultPage("https://b.example.sa/p", "B"),
            ]
        }
    )
    reader = FakeReader({"https://a.example.sa/p": candidate("https://a.example.sa/p", "A page")})

    found = await PageImageSearch(search, reader).search("q", 10)

    assert [c.page_url for c in found] == ["https://a.example.sa/p"]
    assert reader.read_urls == ["https://a.example.sa/p", "https://b.example.sa/p"]


async def test_a_page_listed_twice_is_read_once() -> None:
    search = FakePageSearch(
        {
            "q": [
                SearchResultPage("https://a.example.sa/p", "A"),
                SearchResultPage("https://a.example.sa/p", "A again"),
                SearchResultPage("https://b.example.sa/p", "B"),
            ]
        }
    )
    reader = FakeReader({})

    await PageImageSearch(search, reader).search("q", 3)

    assert reader.read_urls == ["https://a.example.sa/p", "https://b.example.sa/p"]


async def test_a_pdf_or_other_non_page_result_is_not_read() -> None:
    search = FakePageSearch(
        {
            "q": [
                SearchResultPage("https://a.example.sa/leaflet.pdf", "Leaflet"),
                SearchResultPage("https://a.example.sa/p", "Page"),
            ]
        }
    )
    reader = FakeReader({})

    await PageImageSearch(search, reader).search("q", 10)

    assert reader.read_urls == ["https://a.example.sa/p"]


async def test_a_results_file_serves_the_pages_found_for_each_query(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text(
        json.dumps(
            {
                "Panadol Extra Saudi Arabia": [
                    {"url": "https://a.example.sa/p", "title": "Panadol Extra"},
                    {"url": "https://b.example.sa/p", "title": "Other"},
                ]
            }
        ),
        encoding="utf-8",
    )
    search = FilePageSearch(path)

    pages = await search.search("Panadol Extra Saudi Arabia", 1)

    assert pages == [SearchResultPage("https://a.example.sa/p", "Panadol Extra")]
    assert await search.search("a query nobody searched", 10) == []
