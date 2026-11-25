"""Postgres store of every product's look-alike names (`search.similar_name`)."""

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.search.application.ports import StoredSimilarNames
from pharmavique.search.domain.lasa import LasaMatch
from pharmavique.shared_kernel.market import Market

_DELETE = text("DELETE FROM search.similar_name WHERE market = :market")
_INSERT = text(
    "INSERT INTO search.similar_name (market, register_number, english, arabic) "
    "VALUES (:market, :register_number, CAST(:english AS jsonb), CAST(:arabic AS jsonb))"
)
_FIND = text(
    "SELECT english, arabic FROM search.similar_name "
    "WHERE market = :market AND register_number = :register_number"
)
_BATCH = 1000


def _out(matches: tuple[LasaMatch, ...]) -> str:
    return json.dumps(
        [
            {
                "register_number": m.register_number,
                "brand": m.brand,
                "score": m.score,
                "level": m.level,
                "reasons": list(m.reasons),
            }
            for m in matches
        ],
        ensure_ascii=False,
    )


def _in(raw: list[dict[str, Any]]) -> tuple[LasaMatch, ...]:
    return tuple(
        LasaMatch(
            register_number=str(m["register_number"]),
            brand=str(m["brand"]),
            score=float(m["score"]),
            level=str(m["level"]),
            reasons=tuple(str(r) for r in m["reasons"]),
        )
        for m in raw
    )


class PostgresSimilarNameStore:
    """Implements `SimilarNameStore`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def replace(self, market: Market, rows: Sequence[StoredSimilarNames]) -> None:
        values = [
            {
                "market": market.value,
                "register_number": row.register_number,
                "english": _out(row.english),
                "arabic": _out(row.arabic),
            }
            for row in rows
        ]
        async with self._session_factory() as session, session.begin():
            await session.execute(_DELETE, {"market": market.value})
            for start in range(0, len(values), _BATCH):
                await session.execute(_INSERT, values[start : start + _BATCH])

    async def find(self, market: Market, register_number: str) -> StoredSimilarNames | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    _FIND, {"market": market.value, "register_number": register_number}
                )
            ).first()
        if row is None:
            return None
        return StoredSimilarNames(register_number, _in(row.english), _in(row.arabic))
