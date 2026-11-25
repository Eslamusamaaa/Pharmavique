"""What the database knows about each source: how many records and when they were fetched.

One independent query per schema (no joins across schemas). A source the database says nothing
about is simply absent, and the sources page then shows it as unknown, never as zero.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.bootstrap.trust import source_key_for_host


@dataclass(frozen=True, slots=True)
class SourceStat:
    records: int
    last_updated: datetime | None


class SourceStatusReader(Protocol):
    async def read(self) -> dict[str, SourceStat]: ...


_PRODUCTS = text("SELECT count(*), max(provenance_fetched_at) FROM catalog.products")
_LISTS = text("SELECT count(*), max(provenance_fetched_at) FROM catalog.source_list_rows")
_PAIRS = text("SELECT source, count(*), max(fetched_at) FROM interactions.pair GROUP BY source")
_CONTRA = text(
    "SELECT source, count(*), max(fetched_at) FROM interactions.contraindication GROUP BY source"
)
_CHUNKS = text(
    "SELECT coalesce(substring(source_ref FROM '://([^/]+)'), '') AS host, count(*), "
    "max(fetched_at) FROM knowledge.chunk GROUP BY 1"
)


def _merge(into: dict[str, SourceStat], key: str, records: int, at: datetime | None) -> None:
    old = into.get(key)
    if old is None:
        into[key] = SourceStat(records, at)
        return
    latest = max((t for t in (old.last_updated, at) if t is not None), default=None)
    into[key] = SourceStat(old.records + records, latest)


class SqlAlchemySourceStatusReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def read(self) -> dict[str, SourceStat]:
        stats: dict[str, SourceStat] = {}
        async with self._session_factory() as session:
            for key, query in (("sfda-drugs", _PRODUCTS), ("sfda-lists", _LISTS)):
                count, at = (await session.execute(query)).one()
                if count:
                    stats[key] = SourceStat(int(count), at)
            for query in (_PAIRS, _CONTRA):
                for source, count, at in (await session.execute(query)).all():
                    _merge(stats, str(source), int(count), at)
            for host, count, at in (await session.execute(_CHUNKS)).all():
                document_source = source_key_for_host(str(host))
                if document_source is not None:
                    _merge(stats, document_source, int(count), at)
        return stats
