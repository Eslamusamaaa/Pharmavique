"""Ports of the knowledge application layer; adapters live in `infrastructure` (ADR-005, 006)."""

from collections.abc import Sequence
from typing import Protocol

from pharmavique.knowledge.domain.chunks import Chunk, SourceDocument


class DocumentSource(Protocol):
    """The official documents of one list, with their provenance."""

    def documents(self, list_name: str) -> list[SourceDocument]: ...


class ChunkStore(Protocol):
    async def replace(self, list_name: str, chunks: Sequence[Chunk]) -> None:
        """Make the stored chunks of `list_name` exactly `chunks`. Unchanged chunks (same id) keep
        their vectors; chunks that are gone are removed."""
        ...


class Embedder(Protocol):
    """Turns texts into vectors with one model (ADR-005). The adapter is chosen by configuration."""

    @property
    def model(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
