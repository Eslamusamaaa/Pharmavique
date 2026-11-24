"""`Embedder` over an OpenAI-compatible `/embeddings` endpoint (OpenRouter by default, ADR-005/006).

Base URL, model, key and dimensions come from settings. The key is sent only to that endpoint and
never logged. Vectors of the wrong size are refused, because the column holds one size only.
"""

from collections.abc import Sequence

import httpx


class EmbeddingError(RuntimeError):
    pass


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        *,
        api_model: str | None = None,
        send_dimensions: bool = True,
    ) -> None:
        """`model` is the label stored with the vectors; `api_model` is the id the provider wants,
        when it differs (the same bge-m3 is `baai/bge-m3` and `@cf/baai/bge-m3`)."""
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._api_model = api_model or model
        self._send_dimensions = send_dimensions
        self._dimensions = dimensions
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def model(self) -> str:
        return self._model

    @property
    def url(self) -> str:
        return self._url

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict[str, object] = {"model": self._api_model, "input": list(texts)}
        if self._send_dimensions:
            payload["dimensions"] = self._dimensions
        response = await self._client.post(self._url, json=payload, headers=self._headers)
        if response.status_code != 200:
            raise EmbeddingError(f"embedding provider answered HTTP {response.status_code}")
        data = sorted(response.json().get("data", []), key=lambda item: item.get("index", 0))
        vectors = [list(map(float, item["embedding"])) for item in data]
        if len(vectors) != len(texts):
            raise EmbeddingError(f"asked for {len(texts)} vectors, got {len(vectors)}")
        for vector in vectors:
            if len(vector) != self._dimensions:
                raise EmbeddingError(
                    f"model {self._model} returned {len(vector)} dimensions, "
                    f"expected {self._dimensions}"
                )
        return vectors


class FallbackEmbedder:
    """The same model at several providers, tried in order (bge-m3 on Cloudflare, then on
    OpenRouter: identical vectors, so the stored label stays one). Any failure of one provider
    moves the texts to the next; only when all fail is the last error raised."""

    def __init__(self, embedders: Sequence[OpenAICompatibleEmbedder]) -> None:
        if not embedders:
            raise ValueError("at least one embedder is needed")
        if len({e.model for e in embedders}) != 1:
            raise ValueError("backups must store vectors under the same model label")
        self._embedders = list(embedders)

    @property
    def model(self) -> str:
        return self._embedders[0].model

    @property
    def url(self) -> str:
        return self._embedders[0].url

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        for embedder in self._embedders[:-1]:
            try:
                return await embedder.embed(texts)
            except Exception:  # noqa: S112 - any failure of this provider: the next one is asked
                continue
        return await self._embedders[-1].embed(texts)
