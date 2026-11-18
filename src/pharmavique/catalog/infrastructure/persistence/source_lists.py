"""Postgres store for the official SFDA lists and their product links."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.application.list_loading import SourceListRow
from pharmavique.catalog.domain.list_linking import LinkableProduct, RowLink
from pharmavique.catalog.infrastructure.persistence.models import (
    ProductRow,
    SourceListLinkRow,
    SourceListRowRow,
)

_MARKET = "SA"
_CHUNK = 1000


def _chunks(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [items[start : start + _CHUNK] for start in range(0, len(items), _CHUNK)]


def _company_names(data: Mapping[str, Any]) -> list[str]:
    names: list[str] = [str(name) for name in data.get("agents") or []]
    marketing = data.get("marketing_company") or {}
    if marketing.get("name"):
        names.append(str(marketing["name"]))
    names.extend(str(item["name"]) for item in data.get("manufacturers") or [] if item.get("name"))
    return names


class SqlAlchemySourceListStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def linkable_products(self) -> list[LinkableProduct]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProductRow.register_number, ProductRow.data).where(
                    ProductRow.market == _MARKET
                )
            )
            return [
                LinkableProduct.build(
                    number,
                    str((data.get("trade_name") or {}).get("en") or ""),
                    [str(i["name"]) for i in data.get("ingredients") or [] if i.get("name")],
                    _company_names(data),
                )
                for number, data in result.all()
            ]

    async def replace(
        self,
        list_name: str,
        rows: Sequence[SourceListRow],
        links: Mapping[str, Sequence[RowLink]],
    ) -> None:
        row_values = [
            {
                "list_name": list_name,
                "row_key": row.key,
                "entity_key": row.entity_key,
                "link": row.link,
                "cells": [{"label": label, "value": value} for label, value in row.cells],
                "detail": [{"label": label, "value": value} for label, value in row.detail],
                "list_page": row.list_page,
                "provenance_source": row.source,
                "provenance_source_ref": row.source_ref,
                "provenance_fetched_at": row.fetched_at,
                "provenance_snapshot_id": row.snapshot_id,
                "provenance_trust": row.trust,
            }
            for row in rows
        ]
        link_values = [
            {
                "list_name": list_name,
                "row_key": key,
                "market": _MARKET,
                "register_number": link.register_number,
                "confidence": link.confidence,
                "reason": link.reason,
            }
            for key, found in links.items()
            for link in found
        ]
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(SourceListRowRow).where(SourceListRowRow.list_name == list_name)
            )
            for chunk in _chunks(row_values):
                await session.execute(insert(SourceListRowRow), chunk)
            for chunk in _chunks(link_values):
                await session.execute(insert(SourceListLinkRow), chunk)
