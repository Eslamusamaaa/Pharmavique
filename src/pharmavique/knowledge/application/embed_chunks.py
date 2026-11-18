"""Give every stored chunk a vector from the configured embedding model (ADR-006).

Safe to repeat: only chunks without a vector from this model are sent. A provider error stops the
run and is reported, so a free tier's limit never leaves half-written state behind.
"""

from dataclasses import dataclass

from pharmavique.knowledge.application.ports import ChunkVectors, Embedder


@dataclass(frozen=True, slots=True)
class EmbedReport:
    model: str
    embedded: int
    stopped_by: str | None = None


class EmbedChunks:
    def __init__(self, vectors: ChunkVectors, embedder: Embedder, batch_size: int = 32) -> None:
        self._vectors = vectors
        self._embedder = embedder
        self._batch_size = batch_size

    async def run(self, limit: int | None = None) -> EmbedReport:
        model = self._embedder.model
        done = 0
        while limit is None or done < limit:
            size = self._batch_size if limit is None else min(self._batch_size, limit - done)
            batch = await self._vectors.missing(model, size)
            if not batch:
                break
            try:
                vectors = await self._embedder.embed([text for _, text in batch])
            except Exception as error:
                return EmbedReport(model, done, str(error) or type(error).__name__)
            await self._vectors.save(
                model,
                [(chunk_id, vector) for (chunk_id, _), vector in zip(batch, vectors, strict=True)],
            )
            done += len(batch)
        return EmbedReport(model, done)
