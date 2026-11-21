"""PostgreSQL store over the `interactions` schema."""

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.interactions.domain.records import InteractionRecord
from pharmavique.interactions.domain.severity import Severity

_UPSERT = text(
    """
    INSERT INTO interactions.pair (ingredient_a, ingredient_b, severity, source, source_ref,
        snapshot_id, fetched_at, trust)
    VALUES (:a, :b, :severity, :source, :source_ref, :snapshot_id, :fetched_at, :trust)
    ON CONFLICT (ingredient_a, ingredient_b, source) DO UPDATE SET
        severity = EXCLUDED.severity, source_ref = EXCLUDED.source_ref,
        snapshot_id = EXCLUDED.snapshot_id, fetched_at = EXCLUDED.fetched_at,
        trust = EXCLUDED.trust
    """
)
_PAIRS = text(
    """
    SELECT ingredient_a, ingredient_b, severity, source FROM interactions.pair
    WHERE ingredient_a = ANY(:keys) AND ingredient_b = ANY(:keys)
    """
)
_KNOWN = text(
    """
    SELECT ingredient_a AS key FROM interactions.pair WHERE ingredient_a = ANY(:keys)
    UNION
    SELECT ingredient_b FROM interactions.pair WHERE ingredient_b = ANY(:keys)
    """
)
_BATCH = 5_000


class PostgresInteractionStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def replace_source(
        self,
        source: str,
        records: Sequence[InteractionRecord],
        *,
        source_ref: str,
        snapshot_id: str,
        fetched_at: datetime,
        trust: str,
    ) -> None:
        """Make the source's pairs exactly `records`, in one transaction."""
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM interactions.pair WHERE source = :source"), {"source": source}
            )
            for start in range(0, len(records), _BATCH):
                await session.execute(
                    _UPSERT,
                    [
                        {
                            "a": r.ingredient_a,
                            "b": r.ingredient_b,
                            "severity": r.severity.value,
                            "source": source,
                            "source_ref": source_ref,
                            "snapshot_id": snapshot_id,
                            "fetched_at": fetched_at,
                            "trust": trust,
                        }
                        for r in records[start : start + _BATCH]
                    ],
                )

    async def known(self, keys: Collection[str]) -> set[str]:
        async with self._session_factory() as session:
            result = await session.execute(_KNOWN, {"keys": list(keys)})
            return {row.key for row in result}

    async def pairs_among(self, keys: Collection[str]) -> list[InteractionRecord]:
        async with self._session_factory() as session:
            result = await session.execute(_PAIRS, {"keys": list(keys)})
            return [
                InteractionRecord(
                    row.ingredient_a,
                    row.ingredient_b,
                    Severity.from_source(row.severity),
                    row.source,
                )
                for row in result
            ]
