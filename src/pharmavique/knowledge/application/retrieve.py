"""Hybrid retrieval of cited passages: vector similarity and text similarity, fused by rank.

Text search always runs, so retrieval still works without an embedding key or when the provider is
down (ADR-005: fall back instead of failing). Nothing is generated here; passages are returned as
they are stored, each with its official source.
"""

from collections.abc import Sequence

from pharmavique.knowledge.application.ports import Embedder, PassageSearch
from pharmavique.knowledge.domain.retrieval import Passage, fuse

CANDIDATES = 20


class RetrievePassages:
    def __init__(self, search: PassageSearch, embedder: Embedder | None) -> None:
        self._search = search
        self._embedder = embedder

    async def search(
        self, query: str, register_numbers: Sequence[str] = (), limit: int = 6
    ) -> list[Passage]:
        by_vector: list[Passage] = []
        if self._embedder is not None:
            try:
                (vector,) = await self._embedder.embed([query])
                by_vector = await self._search.by_vector(
                    self._embedder.model, vector, register_numbers, CANDIDATES
                )
            except Exception:
                by_vector = []
        by_text = await self._search.by_text(query, register_numbers, CANDIDATES)
        return fuse(by_vector, by_text, limit=limit)
