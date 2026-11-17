"""What other contexts may ask of `search` (published language)."""

from dataclasses import dataclass
from typing import Protocol

from pharmavique.shared_kernel.market import Market


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    market: Market
    limit: int = 10
    include_withdrawn: bool = False


@dataclass(frozen=True, slots=True)
class MatchReason:
    """One signal that found a product: which one, and where it ranked within that signal."""

    signal: str  # "exact" or "fuzzy" (more to come, such as "semantic")
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class SearchMatch:
    market: Market
    register_number: str
    score: float  # fused score; only meaningful for ordering within one result
    exact: bool
    reasons: tuple[MatchReason, ...]


@dataclass(frozen=True, slots=True)
class SearchResult:
    matches: tuple[SearchMatch, ...]


class ProductSearch(Protocol):
    async def search(self, query: SearchQuery) -> SearchResult: ...
