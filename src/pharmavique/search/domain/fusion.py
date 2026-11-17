"""Fuse ranked lists from several retrieval signals into one explainable ranking.

Reciprocal rank fusion (RRF): an item scores `weight / (k + rank)` for each signal that found it,
summed. It needs no calibration between signals, which matters here: a trigram similarity and a
vector distance are not on the same scale. Every result keeps the hits that produced it, so the
caller can say why it was returned ("found by name at rank 2 and by meaning at rank 1").

Exact matches (registration number, barcode) are not "a bit more relevant": they come first.
Whether RRF or a weighted score is better, and the weights, are decided on the evaluation set.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

DEFAULT_K = 60  # the constant from the original RRF paper; flattens the head of each list


@dataclass(frozen=True, slots=True)
class SignalHit:
    signal: str  # "exact", "fuzzy", "semantic", ...
    key: str  # identity of the thing found (a product key)
    rank: int  # 1 for the best hit of that signal
    score: float  # the signal's own score, kept for explanation only


@dataclass(frozen=True, slots=True)
class FusedResult:
    key: str
    score: float  # fused score; not comparable across queries
    hits: tuple[SignalHit, ...]  # one per signal that found it, best rank each
    exact: bool  # found by a signal listed in `first`


def fuse(
    rankings: Sequence[Sequence[SignalHit]],
    *,
    k: int = DEFAULT_K,
    weights: Mapping[str, float] | None = None,
    first: Collection[str] = frozenset(),
    limit: int | None = None,
) -> list[FusedResult]:
    """Merge `rankings` (one list of hits per signal). Deterministic for the same hits.

    Items found by a signal named in `first` come before everything else, ordered by that hit's
    rank; the rest follow by fused score, then best rank, then key.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    weight_of = weights or {}

    best: dict[tuple[str, str], SignalHit] = {}
    for ranking in rankings:
        for hit in ranking:
            slot = (hit.key, hit.signal)
            if slot not in best or hit.rank < best[slot].rank:
                best[slot] = hit

    by_key: dict[str, list[SignalHit]] = {}
    for hit in best.values():
        by_key.setdefault(hit.key, []).append(hit)

    results: list[tuple[tuple[object, ...], FusedResult]] = []
    for key, found in by_key.items():
        ordered = tuple(sorted(found, key=lambda h: (h.signal, h.rank)))
        total = round(sum(weight_of.get(h.signal, 1.0) / (k + h.rank) for h in ordered), 12)
        exact_ranks = [h.rank for h in ordered if h.signal in first]
        exact = bool(exact_ranks)
        sort_key = (
            0 if exact else 1,
            min(exact_ranks) if exact else 0,
            -total,
            min(h.rank for h in ordered),
            key,
        )
        results.append((sort_key, FusedResult(key=key, score=total, hits=ordered, exact=exact)))

    results.sort(key=lambda pair: pair[0])
    fused = [result for _, result in results]
    return fused[:limit] if limit is not None else fused
