"""In-memory search index: the reference adapter.

It scores with the pure-Python trigram code, so the same ranking can be tested and evaluated
without a database. The Postgres adapter must agree with it.
"""

from collections.abc import Sequence

from pharmavique.search.application.ports import IndexHit
from pharmavique.search.domain.documents import ProductKey, SearchDocument
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.trigrams import similarity

INGREDIENT_WEIGHT = 0.9  # a match on an ingredient counts a little less than one on a name


def score_of(document: SearchDocument, text: str) -> float:
    best_name = max((similarity(text, name) for name in document.names), default=0.0)
    return max(best_name, INGREDIENT_WEIGHT * similarity(text, document.ingredients))


class InMemorySearchIndex:
    def __init__(self) -> None:
        self._documents: dict[ProductKey, SearchDocument] = {}

    def __len__(self) -> int:
        return len(self._documents)

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        for document in documents:
            self._documents[document.key] = document

    async def find_exact(
        self, market: Market, register_number: str, include_withdrawn: bool
    ) -> list[IndexHit]:
        wanted = register_number.strip().casefold()
        return [
            IndexHit(key=document.key, score=1.0)
            for document in self._documents.values()
            if document.key.market is market
            and document.key.register_number.casefold() == wanted
            and (include_withdrawn or not document.withdrawn)
        ]

    async def find_similar(
        self,
        market: Market,
        text: str,
        limit: int,
        min_score: float,
        include_withdrawn: bool,
    ) -> list[IndexHit]:
        scored = [
            IndexHit(key=document.key, score=score_of(document, text))
            for document in self._documents.values()
            if document.key.market is market and (include_withdrawn or not document.withdrawn)
        ]
        kept = [hit for hit in scored if hit.score >= min_score]
        kept.sort(key=lambda hit: (-hit.score, hit.key.register_number))
        return kept[:limit]
