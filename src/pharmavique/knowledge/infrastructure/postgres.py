"""PostgreSQL chunk store over the `knowledge` schema (ADR-006).

`replace` makes a list's chunks exactly the given ones in one transaction. A chunk whose id (a hash
of its list, row and text) is unchanged keeps its vector, so a rebuild never forces a re-embed of
text that did not change.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.knowledge.domain.chunks import Chunk
from pharmavique.knowledge.domain.retrieval import Passage

_UPSERT = text(
    """
    INSERT INTO knowledge.chunk (chunk_id, list_name, row_key, position, title, text, source_ref,
        snapshot_id, fetched_at, trust, ocr, published, register_numbers, updated_at)
    VALUES (:chunk_id, :list_name, :row_key, :position, :title, :text, :source_ref,
        :snapshot_id, :fetched_at, :trust, :ocr, :published, :register_numbers, now())
    ON CONFLICT (chunk_id) DO UPDATE SET
        position = EXCLUDED.position, title = EXCLUDED.title, source_ref = EXCLUDED.source_ref,
        snapshot_id = EXCLUDED.snapshot_id, fetched_at = EXCLUDED.fetched_at,
        trust = EXCLUDED.trust, ocr = EXCLUDED.ocr, published = EXCLUDED.published,
        register_numbers = EXCLUDED.register_numbers, updated_at = now()
    """
)
_DELETE_GONE = text(
    "DELETE FROM knowledge.chunk WHERE list_name = :list_name AND NOT (chunk_id = ANY(:ids))"
)


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class PostgresChunkStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def replace(self, list_name: str, chunks: Sequence[Chunk]) -> None:
        async with self._session_factory() as session, session.begin():
            await self._upsert(session, chunks)
            await session.execute(
                _DELETE_GONE,
                {"list_name": list_name, "ids": [chunk.chunk_id for chunk in chunks]},
            )

    async def add(self, list_name: str, chunks: Sequence[Chunk]) -> None:
        """Upsert only: every other chunk of the list stays, and so does its vector."""
        async with self._session_factory() as session, session.begin():
            await self._upsert(session, [c for c in chunks if c.list_name == list_name])

    async def row_keys(self, list_name: str) -> set[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT DISTINCT row_key FROM knowledge.chunk WHERE list_name = :list_name"),
                {"list_name": list_name},
            )
            return {str(row[0]) for row in result}

    @staticmethod
    async def _upsert(session: AsyncSession, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            return
        await session.execute(
            _UPSERT,
            [
                {
                    "chunk_id": chunk.chunk_id,
                    "list_name": chunk.list_name,
                    "row_key": chunk.row_key,
                    "position": chunk.position,
                    "title": chunk.title,
                    "text": chunk.text,
                    "source_ref": chunk.source_ref,
                    "snapshot_id": chunk.snapshot_id,
                    "fetched_at": _when(chunk.fetched_at),
                    "trust": chunk.trust,
                    "ocr": chunk.ocr,
                    "published": chunk.published,
                    "register_numbers": list(chunk.register_numbers),
                }
                for chunk in chunks
            ],
        )


# ---- vectors and retrieval --------------------------------------------------------------------
_MISSING = text(
    """
    SELECT chunk_id, title || E'\n' || text AS body FROM knowledge.chunk
    WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM :model
    ORDER BY list_name, row_key, position
    LIMIT :limit
    """
)
_SAVE = text(
    """
    UPDATE knowledge.chunk SET embedding = CAST(:vector AS vector), embedding_model = :model
    WHERE chunk_id = :chunk_id
    """
)
_BY_VECTOR = text(
    """
    SELECT chunk_id, list_name, title, text, source_ref, published, register_numbers, ocr
    FROM knowledge.chunk
    WHERE embedding_model = :model
      AND (cardinality(CAST(:numbers AS text[])) = 0
           OR register_numbers && CAST(:numbers AS text[]))
    ORDER BY embedding <=> CAST(:vector AS vector)
    LIMIT :limit
    """
)
_BY_TEXT = text(
    """
    SELECT chunk_id, list_name, title, text, source_ref, published, register_numbers, ocr
    FROM knowledge.chunk
    WHERE (cardinality(CAST(:numbers AS text[])) = 0
           OR register_numbers && CAST(:numbers AS text[]))
      AND (text % :query OR title % :query OR text ILIKE :like OR title ILIKE :like)
    ORDER BY greatest(similarity(text, :query), similarity(title, :query)) DESC
    LIMIT :limit
    """
)


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.7g}" for value in vector) + "]"


def _passage(row: Any) -> Passage:
    return Passage(
        chunk_id=row.chunk_id,
        list_name=row.list_name,
        title=row.title,
        text=row.text,
        source_ref=row.source_ref,
        published=row.published,
        register_numbers=tuple(row.register_numbers or ()),
        ocr=bool(row.ocr),
    )


class PostgresChunkVectors:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def missing(self, model: str, limit: int) -> list[tuple[str, str]]:
        async with self._session_factory() as session:
            rows = (await session.execute(_MISSING, {"model": model, "limit": limit})).all()
        return [(row.chunk_id, row.body) for row in rows]

    async def save(self, model: str, vectors: Sequence[tuple[str, list[float]]]) -> None:
        if not vectors:
            return
        async with self._session_factory() as session, session.begin():
            await session.execute(
                _SAVE,
                [
                    {"chunk_id": chunk_id, "vector": _vector_literal(vector), "model": model}
                    for chunk_id, vector in vectors
                ],
            )


class PostgresPassageSearch:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def by_vector(
        self, model: str, vector: list[float], register_numbers: Sequence[str], limit: int
    ) -> list[Passage]:
        params = {
            "model": model,
            "vector": _vector_literal(vector),
            "numbers": list(register_numbers),
            "limit": limit,
        }
        async with self._session_factory() as session:
            rows = (await session.execute(_BY_VECTOR, params)).all()
        return [_passage(row) for row in rows]

    async def by_text(
        self, query: str, register_numbers: Sequence[str], limit: int
    ) -> list[Passage]:
        params = {
            "query": query,
            "like": f"%{query}%",
            "numbers": list(register_numbers),
            "limit": limit,
        }
        async with self._session_factory() as session:
            rows = (await session.execute(_BY_TEXT, params)).all()
        return [_passage(row) for row in rows]
