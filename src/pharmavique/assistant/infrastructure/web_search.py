"""`WebSearch` over Tavily (ADR-017).

`POST https://api.tavily.com/search` with `Authorization: Bearer <key>`; the request and response
fields are the ones in Tavily's API reference (read 2026-11-22). Only the search provider's snippets
are used: no page is ever fetched. The key goes only in the header and never in an error message.
"""

from typing import Any

import httpx

TAVILY_URL = "https://api.tavily.com/search"
MAX_SNIPPET = 600  # characters of one result given to the model


class WebSearchError(Exception):
    """The search provider could not answer (a status or a connection problem; never the key)."""


class TavilyWebSearch:
    def __init__(
        self, api_key: str, client: httpx.AsyncClient | None = None, timeout: float = 15.0
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        payload = {
            "query": query,
            "search_depth": "basic",  # one credit; "advanced" costs two
            "max_results": limit,
            "topic": "general",
            "include_answer": False,
        }
        try:
            response = await self._client.post(TAVILY_URL, json=payload, headers=self._headers)
        except httpx.TransportError as error:
            raise WebSearchError(
                f"web search connection failed ({type(error).__name__})"
            ) from error
        if response.status_code != 200:
            raise WebSearchError(f"web search provider answered HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise WebSearchError(
                "web search provider answered something that is not JSON"
            ) from error
        results = body.get("results") if isinstance(body, dict) else None
        found: list[dict[str, Any]] = []
        for item in results or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            found.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": str(item["url"]),
                    "snippet": str(item.get("content") or "")[:MAX_SNIPPET],
                }
            )
        return found
