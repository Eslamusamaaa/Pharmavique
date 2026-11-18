"""Retrieved passages and how two ranked lists are fused (reciprocal rank fusion).

A passage is a chunk of an official document with everything needed to cite it. Retrieval never
rewrites text: the assistant quotes and cites passages as they are.
"""

from collections.abc import Sequence
from dataclasses import dataclass

RRF_K = 60  # the usual constant: dampens the weight of the very top ranks


@dataclass(frozen=True, slots=True)
class Passage:
    chunk_id: str
    list_name: str
    title: str
    text: str
    source_ref: str
    published: str | None
    register_numbers: tuple[str, ...]
    ocr: bool


def fuse(*rankings: Sequence[Passage], limit: int) -> list[Passage]:
    """Order passages by the sum of 1 / (k + rank) over the rankings they appear in."""
    scores: dict[str, float] = {}
    first_seen: dict[str, Passage] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            first_seen.setdefault(item.chunk_id, item)
    order = sorted(scores, key=lambda chunk_id: -scores[chunk_id])
    return [first_seen[chunk_id] for chunk_id in order[:limit]]
