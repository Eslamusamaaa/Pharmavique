"""Search use cases: answer a query, and rebuild the index from the catalog."""

from pharmavique.search.application.ports import IndexHit, ProductSource, SearchIndex
from pharmavique.search.contracts.queries import (
    MatchReason,
    SearchMatch,
    SearchQuery,
    SearchResult,
)
from pharmavique.search.domain.documents import build_document
from pharmavique.search.domain.fusion import SignalHit, fuse
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.text import normalize_text

DEFAULT_MIN_SCORE = 0.2  # a starting point; tuned on the evaluation set, not by feel
DEFAULT_CANDIDATES = 50  # how many candidates each signal returns before fusion
EXACT = "exact"
FUZZY = "fuzzy"


def _key(hit: IndexHit) -> str:
    return f"{hit.key.market.value}:{hit.key.register_number}"


def _signal_hits(signal: str, hits: list[IndexHit]) -> list[SignalHit]:
    return [
        SignalHit(signal=signal, key=_key(hit), rank=rank, score=hit.score)
        for rank, hit in enumerate(hits, 1)
    ]


class SearchProductsHandler:
    """Implements `ProductSearch`: exact and fuzzy signals, fused, with reasons."""

    def __init__(
        self,
        index: SearchIndex,
        *,
        min_score: float = DEFAULT_MIN_SCORE,
        candidates: int = DEFAULT_CANDIDATES,
    ) -> None:
        self._index = index
        self._min_score = min_score
        self._candidates = candidates

    async def search(self, query: SearchQuery) -> SearchResult:
        if query.limit < 1:
            raise ValueError("limit must be at least 1")
        raw = query.text.strip()
        normalized = normalize_text(raw)
        if not normalized:
            return SearchResult(matches=())

        exact = await self._index.find_exact(query.market, raw, query.include_withdrawn)
        similar = await self._index.find_similar(
            query.market,
            normalized,
            self._candidates,
            self._min_score,
            query.include_withdrawn,
        )
        fused = fuse(
            [_signal_hits(EXACT, exact), _signal_hits(FUZZY, similar)],
            first={EXACT},
            limit=query.limit,
        )
        matches: list[SearchMatch] = []
        for result in fused:
            market, register_number = result.key.split(":", 1)
            matches.append(
                SearchMatch(
                    market=Market(market),
                    register_number=register_number,
                    score=result.score,
                    exact=result.exact,
                    reasons=tuple(
                        MatchReason(signal=hit.signal, rank=hit.rank, score=hit.score)
                        for hit in result.hits
                    ),
                )
            )
        return SearchResult(matches=tuple(matches))


class RebuildIndexHandler:
    """Reads every product of a market from the source and upserts it. Safe to repeat."""

    def __init__(self, source: ProductSource, index: SearchIndex, page_size: int = 500) -> None:
        self._source = source
        self._index = index
        self._page_size = page_size

    async def rebuild(self, market: Market) -> int:
        count = 0
        async for page in self._source.pages(market, self._page_size):
            await self._index.upsert([build_document(product) for product in page])
            count += len(page)
        return count
