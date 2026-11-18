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
    ) -> None:
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._dimensions = dimensions
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self._model, "input": list(texts), "dimensions": self._dimensions}
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
