"""The Tavily adapter of the `WebSearch` port, against a mocked HTTP transport."""

import json

import httpx
import pytest

from pharmavique.assistant.infrastructure.web_search import TavilyWebSearch, WebSearchError


def adapter(
    handler: httpx.MockTransport | None = None, key: str = "tvly-secret"
) -> TavilyWebSearch:
    client = httpx.AsyncClient(transport=handler)
    return TavilyWebSearch(key, client=client)


async def test_the_request_is_a_bearer_post_with_the_documented_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"query": "q", "results": [], "images": []})

    await adapter(httpx.MockTransport(handler)).search("Cataflam 50 mg", 4)

    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://api.tavily.com/search"
    assert request.headers["authorization"] == "Bearer tvly-secret"
    body = json.loads(request.content)
    assert body["query"] == "Cataflam 50 mg"
    assert body["max_results"] == 4
    assert body["search_depth"] == "basic"
    assert body["include_answer"] is False


async def test_results_become_title_url_and_a_short_snippet() -> None:
    long_text = "word " * 400

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Cataflam",
                        "url": "https://x.test/a",
                        "content": long_text,
                        "score": 0.9,
                    },
                    {"title": "No text", "url": "https://x.test/b"},
                    {"title": "No address", "content": "text"},
                ]
            },
        )

    found = await adapter(httpx.MockTransport(handler)).search("cataflam", 5)

    assert [r["url"] for r in found] == ["https://x.test/a", "https://x.test/b"]
    assert found[0]["title"] == "Cataflam"
    assert len(found[0]["snippet"]) <= 600
    assert found[1]["snippet"] == ""


@pytest.mark.parametrize("status", [401, 429, 432, 500])
async def test_a_provider_error_names_the_status_and_never_the_key(status: int) -> None:
    client = httpx.MockTransport(lambda request: httpx.Response(status))

    with pytest.raises(WebSearchError) as raised:
        await adapter(client).search("cataflam", 3)

    assert str(status) in str(raised.value)
    assert "tvly-secret" not in str(raised.value)


async def test_a_dropped_connection_is_a_web_search_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("closed", request=request)

    with pytest.raises(WebSearchError):
        await adapter(httpx.MockTransport(handler)).search("cataflam", 3)


async def test_an_answer_that_is_not_json_is_a_web_search_error() -> None:
    client = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))

    with pytest.raises(WebSearchError):
        await adapter(client).search("cataflam", 3)
