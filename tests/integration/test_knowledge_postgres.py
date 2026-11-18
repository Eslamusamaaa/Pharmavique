"""The knowledge chunk store against the real Postgres (pgvector schema from knowledge_0001)."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.knowledge.domain.chunks import SourceDocument, chunk_document
from pharmavique.knowledge.infrastructure.postgres import PostgresChunkStore

pytestmark = pytest.mark.integration


def doc(row_key: str, body: str, list_name: str = "dhpc") -> SourceDocument:
    return SourceDocument(
        list_name=list_name,
        row_key=row_key,
        title=f"title {row_key}",
        text=body,
        source_ref=f"https://www.sfda.gov.sa/{row_key}",
        snapshot_id="lists-1",
        fetched_at="2026-11-18T10:00:00+00:00",
        trust="official",
        ocr=row_key.startswith("ocr"),
        published="2021-01-10",
    )


@pytest.fixture
async def factory(migrated_url: URL) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(migrated_url.render_as_string(hide_password=False))
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE knowledge.chunk"))
    yield create_session_factory(engine)
    await engine.dispose()


async def rows(factory: async_sessionmaker[AsyncSession]) -> list[tuple[str, str, bool, str]]:
    async with factory() as session:
        result = await session.execute(
            text("SELECT list_name, row_key, ocr, text FROM knowledge.chunk ORDER BY row_key")
        )
        return [(row[0], row[1], row[2], row[3]) for row in result]


async def test_replacing_a_list_stores_its_chunks_and_drops_what_is_gone(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresChunkStore(factory)
    first = chunk_document(doc("a#1", "Letter one.")) + chunk_document(doc("ocr#2", "Scanned."))
    await store.replace("dhpc", first)
    other = chunk_document(doc("r#1", "A recall.", list_name="drugs-circulars"))
    await store.replace("drugs-circulars", other)

    assert await rows(factory) == [
        ("dhpc", "a#1", False, "Letter one."),
        ("dhpc", "ocr#2", True, "Scanned."),
        ("drugs-circulars", "r#1", False, "A recall."),
    ]

    await store.replace("dhpc", chunk_document(doc("a#1", "Letter one.")))

    assert [row[1] for row in await rows(factory)] == ["a#1", "r#1"]  # other lists untouched


async def test_an_unchanged_chunk_keeps_its_vector_when_the_list_is_rebuilt(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresChunkStore(factory)
    chunks = chunk_document(doc("a#1", "Letter one."))
    await store.replace("dhpc", chunks)
    async with factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE knowledge.chunk SET embedding = array_fill(0.5, ARRAY[1024])::vector, "
                "embedding_model = 'fake' WHERE chunk_id = :id"
            ),
            {"id": chunks[0].chunk_id},
        )

    await store.replace("dhpc", chunks)

    async with factory() as session:
        model = await session.scalar(text("SELECT embedding_model FROM knowledge.chunk"))
    assert model == "fake"
