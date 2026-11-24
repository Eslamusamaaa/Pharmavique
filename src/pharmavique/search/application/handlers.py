"""Search use cases: answer a query, and rebuild the index from the catalog."""

from pharmavique.search.application.ports import IndexHit, ProductSource, SearchIndex
from pharmavique.search.contracts.queries import (
    MatchReason,
    SearchMatch,
    SearchQuery,
    SearchResult,
)
from pharmavique.search.domain.arabic_names import english_names
from pharmavique.search.domain.documents import build_document
from pharmavique.search.domain.fusion import SignalHit, fuse
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.names import NAME_NOISE
from pharmavique.shared_kernel.text import normalize_text

DEFAULT_MIN_SCORE = 0.2  # a starting point; tuned on the evaluation set, not by feel
DEFAULT_CANDIDATES = 50  # how many candidates each signal returns before fusion
EXACT = "exact"
FUZZY = "fuzzy"
# Shorter readings of a long query ("PANADOL EXTRA Paracetamol 500 mg + Caffeine 65 mg"): extra
# words push a name's similarity down, so the name itself is also looked up on its own.
FUZZY_CORE = "fuzzy_core"  # the words that are not numbers, units or form words
FUZZY_LEAD = "fuzzy_lead"  # the first two of those words
FUZZY_FIRST = "fuzzy_first"  # the first of those words
ARABIC_NAME = "arabic_name"  # the English generic name an Arabic query spells ("انسولين")
# How much a reading is trusted against the query as typed: the best reading of a product wins.
FACTORS = {FUZZY: 1.0, FUZZY_CORE: 0.95, FUZZY_LEAD: 0.9, FUZZY_FIRST: 0.5, ARABIC_NAME: 1.0}
MIN_VARIANT_LENGTH = 3


def variants(normalized: str) -> list[tuple[str, str]]:
    """(signal, text) of the shorter readings of a query that differ from the query itself."""
    core = [
        word
        for word in normalized.split()
        if word not in NAME_NOISE and not any(char.isdigit() for char in word)
    ]
    found: list[tuple[str, str]] = []
    seen = {normalized}
    for signal, words in ((FUZZY_CORE, core), (FUZZY_LEAD, core[:2]), (FUZZY_FIRST, core[:1])):
        text = " ".join(words)
        if len(text) >= MIN_VARIANT_LENGTH and text not in seen:
            seen.add(text)
            found.append((signal, text))
    return found


def arabic_readings(normalized: str) -> list[str]:
    """The English generic names an Arabic query spells, as typed or without its numbers
    ("ليفوثيروكسين 50" reads as "levothyroxine")."""
    core = " ".join(word for word in normalized.split() if not any(c.isdigit() for c in word))
    found: list[str] = []
    for text in (normalized, core):
        for name in english_names(text):
            if name not in found:
                found.append(name)
    return found


def _key(hit: IndexHit) -> str:
    return f"{hit.key.market.value}:{hit.key.register_number}"


def _signal_hits(signal: str, hits: list[IndexHit]) -> list[SignalHit]:
    return [
        SignalHit(signal=signal, key=_key(hit), rank=rank, score=hit.score)
        for rank, hit in enumerate(hits, 1)
    ]


def _best_reading(readings: list[tuple[str, list[IndexHit]]]) -> list[SignalHit]:
    """One ranking from every reading of the query: each product keeps the reading that fits it
    best (its similarity times how far that reading is trusted) and is named by that reading."""
    best: dict[str, tuple[float, str, IndexHit]] = {}
    for signal, hits in readings:
        for hit in hits:
            score = hit.score * FACTORS[signal]
            key = _key(hit)
            if key not in best or score > best[key][0]:
                best[key] = (score, signal, hit)
    ordered = sorted(best.values(), key=lambda item: (-item[0], item[2].key.register_number))
    return [
        SignalHit(signal=signal, key=_key(hit), rank=rank, score=score)
        for rank, (score, signal, hit) in enumerate(ordered, 1)
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
        readings = [(FUZZY, similar)]
        for signal, text in variants(normalized):
            more = await self._index.find_similar(
                query.market, text, self._candidates, self._min_score, query.include_withdrawn
            )
            readings.append((signal, more))
        for text in arabic_readings(normalized):
            more = await self._index.find_similar(
                query.market, text, self._candidates, self._min_score, query.include_withdrawn
            )
            readings.append((ARABIC_NAME, more))
        fused = fuse(
            [_signal_hits(EXACT, exact), _best_reading(readings)],
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
