"""PostgreSQL chunk store over the `knowledge` schema (ADR-006).

`replace` makes a list's chunks exactly the given ones in one transaction. A chunk whose id (a hash
of its list, row and text) is unchanged keeps its vector, so a rebuild never forces a re-embed of
text that did not change.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.knowledge.domain.chunks import Chunk

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
            if chunks:
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
            await session.execute(
                _DELETE_GONE,
                {"list_name": list_name, "ids": [chunk.chunk_id for chunk in chunks]},
            )
