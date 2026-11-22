"""Ports of the knowledge application layer; adapters live in `infrastructure` (ADR-005, 006)."""

from collections.abc import Sequence
from typing import Protocol

from pharmavique.knowledge.domain.chunks import Chunk, SourceDocument
from pharmavique.knowledge.domain.retrieval import Passage


class DocumentSource(Protocol):
    """The official documents of one list, with their provenance."""

    def documents(self, list_name: str) -> list[SourceDocument]: ...


class ChunkStore(Protocol):
    async def replace(self, list_name: str, chunks: Sequence[Chunk]) -> None:
        """Make the stored chunks of `list_name` exactly `chunks`. Unchanged chunks (same id) keep
        their vectors; chunks that are gone are removed."""
        ...

    async def add(self, list_name: str, chunks: Sequence[Chunk]) -> None:
        """Store these chunks and keep every other chunk of the list, vectors included."""
        ...

    async def row_keys(self, list_name: str) -> set[str]:
        """The row keys of `list_name` that have at least one stored chunk."""
        ...


class Embedder(Protocol):
    """Turns texts into vectors with one model (ADR-005). The adapter is chosen by configuration."""

    @property
    def model(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ChunkVectors(Protocol):
    """Where chunk vectors are kept; vectors of different models never mix."""

    async def missing(self, model: str, limit: int) -> list[tuple[str, str]]:
        """(chunk id, text) of chunks that have no vector from `model` yet."""
        ...

    async def save(self, model: str, vectors: Sequence[tuple[str, list[float]]]) -> None: ...


class PassageSearch(Protocol):
    """Two independent rankings of stored chunks; fusion happens in the application layer."""

    async def by_vector(
        self, model: str, vector: list[float], register_numbers: Sequence[str], limit: int
    ) -> list[Passage]: ...

    async def by_text(
        self, query: str, register_numbers: Sequence[str], limit: int
    ) -> list[Passage]: ...
