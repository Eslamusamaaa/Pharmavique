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
        documents = self._source.documents(list_name)
        chunks: list[Chunk] = []
        empty = 0
        for document in documents:
            found = chunk_document(document)
            if not found:
                empty += 1
            chunks.extend(found)
        await self._store.replace(list_name, chunks)
        return ChunkReport(
            list_name=list_name,
            documents=len(documents),
            empty=empty,
            chunks=len(chunks),
            ocr_chunks=sum(1 for chunk in chunks if chunk.ocr),
        )
