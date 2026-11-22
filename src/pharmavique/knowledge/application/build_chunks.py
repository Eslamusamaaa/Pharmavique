"""Use case: rebuild the knowledge chunks of one official list. Safe to repeat."""

from dataclasses import dataclass

from pharmavique.knowledge.application.ports import ChunkStore, DocumentSource
from pharmavique.knowledge.domain.chunks import Chunk, chunk_document


@dataclass(frozen=True, slots=True)
class ChunkReport:
    list_name: str
    documents: int
    empty: int
    chunks: int
    ocr_chunks: int


class BuildChunks:
    def __init__(self, source: DocumentSource, store: ChunkStore) -> None:
        self._source = source
        self._store = store

    async def run(self, list_name: str) -> ChunkReport:
        """Make the stored chunks of the list exactly those of the source (a full rebuild)."""
        chunks, report = self._cut(list_name)
        await self._store.replace(list_name, chunks)
        return report

    async def run_additive(self, list_name: str) -> ChunkReport:
        """Add the source's chunks and keep everything already stored. For a source that holds only
        the new rows of a list: a full rebuild from it would erase the rest."""
        chunks, report = self._cut(list_name)
        if chunks:
            await self._store.add(list_name, chunks)
        return report

    def _cut(self, list_name: str) -> tuple[list[Chunk], ChunkReport]:
        documents = self._source.documents(list_name)
        chunks: list[Chunk] = []
        empty = 0
        for document in documents:
            found = chunk_document(document)
            if not found:
                empty += 1
            chunks.extend(found)
        return chunks, ChunkReport(
            list_name=list_name,
            documents=len(documents),
            empty=empty,
            chunks=len(chunks),
            ocr_chunks=sum(1 for chunk in chunks if chunk.ocr),
        )
