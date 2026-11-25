"""Ports of the search application layer. Adapters live in `infrastructure`."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from pharmavique.search.domain.documents import ProductKey, ProductToIndex, SearchDocument
from pharmavique.search.domain.lasa import LasaMatch
from pharmavique.shared_kernel.market import Market


@dataclass(frozen=True, slots=True)
class IndexHit:
    key: ProductKey
    score: float  # the signal's own score; the order of a hit list is its ranking


class SearchIndex(Protocol):
    """The projection search queries. Postgres is one adapter, memory is another."""

    async def upsert(self, documents: Sequence[SearchDocument]) -> None:
        """Insert or replace by key. Repeating a batch changes nothing."""
        ...

    async def find_exact(
        self, market: Market, register_number: str, include_withdrawn: bool
    ) -> list[IndexHit]: ...

    async def find_similar(
        self,
        market: Market,
        text: str,
        limit: int,
        min_score: float,
        include_withdrawn: bool,
    ) -> list[IndexHit]:
        """Trigram similarity of normalized `text` to names and ingredients, best first."""
        ...


class ProductSource(Protocol):
    """Where products come from. The adapter reads the catalog's published contract."""

    def pages(self, market: Market, page_size: int) -> AsyncIterator[Sequence[ProductToIndex]]: ...


@dataclass(frozen=True, slots=True)
class ProductNames:
    """A product's trade names, as the similar-names index reads them."""

    register_number: str
    en: str | None
    ar: str | None


@dataclass(frozen=True, slots=True)
class StoredSimilarNames:
    """The look-alike names of one product, computed by the daily refresh."""

    register_number: str
    english: tuple[LasaMatch, ...]
    arabic: tuple[LasaMatch, ...]


class NameSource(Protocol):
    """Every product's trade names. The adapter reads the catalog's published contract."""

    async def names(self, market: Market) -> Sequence[ProductNames]: ...


class SimilarNameStore(Protocol):
    async def replace(self, market: Market, rows: Sequence[StoredSimilarNames]) -> None:
        """Replace every row of the market at once (readers see the old rows or the new ones)."""
        ...

    async def find(self, market: Market, register_number: str) -> StoredSimilarNames | None:
        """The stored look-alikes of one product, or None when it was not computed."""
        ...
