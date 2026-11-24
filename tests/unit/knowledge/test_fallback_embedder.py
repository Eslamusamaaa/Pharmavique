"""The embedder goes on to the same model at the next provider when one fails."""

import httpx
import pytest

from pharmavique.knowledge.infrastructure.openai_embedder import (
    EmbeddingError,
    FallbackEmbedder,
    OpenAICompatibleEmbedder,
)


def embedder(status: int, model: str = "baai/bge-m3") -> OpenAICompatibleEmbedder:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5, 0.5]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleEmbedder("https://x.test", "k", model, 2, client)


async def test_a_failing_provider_moves_to_the_next() -> None:
    assert await FallbackEmbedder([embedder(503), embedder(200)]).embed(["q"]) == [[0.5, 0.5]]


async def test_when_all_fail_the_last_error_is_raised() -> None:
    with pytest.raises(EmbeddingError):
        await FallbackEmbedder([embedder(503), embedder(429)]).embed(["q"])


def test_backups_must_store_vectors_under_one_label() -> None:
    with pytest.raises(ValueError, match="same model label"):
        FallbackEmbedder([embedder(200), embedder(200, model="other")])
