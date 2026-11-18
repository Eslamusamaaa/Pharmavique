"""The OpenAI-compatible embedder, against a fake HTTP endpoint."""

import json

import httpx
import pytest

from pharmavique.knowledge.infrastructure.openai_embedder import (
    EmbeddingError,
    OpenAICompatibleEmbedder,
)


def embedder(handler: object, dimensions: int = 3) -> OpenAICompatibleEmbedder:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return OpenAICompatibleEmbedder("https://api.test/v1/", "secret", "m-1", dimensions, client)


async def test_vectors_come_back_in_input_order_and_the_key_goes_in_the_header() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        data = [
            {"index": 1, "embedding": [0.0, 1.0, 0.0]},
            {"index": 0, "embedding": [1.0, 0.0, 0.0]},
        ]
        return httpx.Response(200, json={"data": data})

    vectors = await embedder(handler).embed(["a", "b"])

    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert seen["url"] == "https://api.test/v1/embeddings"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"] == {"model": "m-1", "input": ["a", "b"], "dimensions": 3}


async def test_a_provider_error_is_an_embedding_error_without_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, text="gateway timeout")

    with pytest.raises(EmbeddingError, match="HTTP 504") as raised:
        await embedder(handler).embed(["a"])
    assert "secret" not in str(raised.value)


async def test_vectors_of_the_wrong_size_are_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]})

    with pytest.raises(EmbeddingError, match="2 dimensions"):
        await embedder(handler).embed(["a"])
