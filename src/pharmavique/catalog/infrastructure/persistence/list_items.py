"""Read the official-list rows that are linked to one product (shortages, safety notices)."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.contracts.queries import ListItem
from pharmavique.catalog.infrastructure.persistence.models import (
    SourceListLinkRow,
    SourceListRowRow,
)
from pharmavique.shared_kernel.market import Market


def _pairs(items: Sequence[Any]) -> tuple[tuple[str, str], ...]:
    return tuple((str(i.get("label", "")), str(i.get("value", ""))) for i in items)


class SqlAlchemyListItemReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_items(
        self, market: Market, register_number: str, list_names: Sequence[str]
    ) -> tuple[ListItem, ...]:
        if not list_names:
            return ()
        statement = (
            select(SourceListRowRow, SourceListLinkRow)
            .join(
                SourceListLinkRow,
                (SourceListLinkRow.list_name == SourceListRowRow.list_name)
                & (SourceListLinkRow.row_key == SourceListRowRow.row_key),
            )
            .where(
                SourceListLinkRow.market == market.value,
                SourceListLinkRow.register_number == register_number,
                SourceListRowRow.list_name.in_(list_names),
            )
            .order_by(
                SourceListLinkRow.confidence,  # "matched" sorts before "possible"
                SourceListRowRow.list_name,
                SourceListRowRow.row_key,
            )
        )
        async with self._session_factory() as session:
            found = (await session.execute(statement)).all()
        return tuple(
            ListItem(
                list_name=row.list_name,
                confidence=link.confidence,
                reason=link.reason,
                cells=_pairs(row.cells),
                detail=_pairs(row.detail),
                facets=tuple(sorted((str(k), str(v)) for k, v in row.facets.items())),
                link=row.link,
                source_ref=row.provenance_source_ref,
                fetched_at=row.provenance_fetched_at,
                trust=row.provenance_trust,
            )
            for row, link in found
        )
