"""A `PageSearch` that reads its results from a JSON file.

The file maps each search phrase to the pages found for it:
`{"<query>": [{"url": "https://...", "title": "..."}, ...], ...}`. Any search runner (an API
client, a person, an assistant) can fill it; the rest of the pipeline does not care which.
"""

import json
from pathlib import Path

from pharmavique.media.application.page_search import SearchResultPage


class FilePageSearch:
    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._results: dict[str, list[SearchResultPage]] = {
            query: [SearchResultPage(item["url"], item.get("title", "")) for item in items]
            for query, items in raw.items()
        }

    async def search(self, query: str, limit: int) -> list[SearchResultPage]:
        return self._results.get(query, [])[:limit]
