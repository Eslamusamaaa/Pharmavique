"""Use case: keep the rows of an official SFDA list in the catalog and link them to products.

Safe to repeat: a list is replaced as a whole, so loading the same rows again changes nothing.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from pharmavique.catalog.domain.list_facets import facets_for
from pharmavique.catalog.domain.list_linking import LinkableProduct, ProductLinkIndex, RowLink


@dataclass(frozen=True, slots=True)
class SourceListRow:
    key: str
    entity_key: str
    link: str | None
    cells: tuple[tuple[str, str], ...]  # (column label, value), as the site shows them
    list_page: int
    source: str
    source_ref: str
    snapshot_id: str
    fetched_at: datetime | None
    trust: str
    detail: tuple[tuple[str, str], ...] = ()  # (label, value) from the row's detail page, if any
    facets: Mapping[str, str] = field(default_factory=dict)  # clean values to filter by


class SourceListStore(Protocol):
    async def linkable_products(self) -> list[LinkableProduct]: ...

    async def replace(
        self,
        list_name: str,
        rows: Sequence[SourceListRow],
        links: Mapping[str, Sequence[RowLink]],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ListLoadReport:
    list_name: str
    rows: int
    rows_with_links: int
    matched_links: int
    possible_links: int


class LoadSourceList:
    def __init__(self, store: SourceListStore) -> None:
        self._store = store

    async def run(self, list_name: str, rows: Sequence[SourceListRow]) -> ListLoadReport:
        index = ProductLinkIndex(await self._store.linkable_products())
        rows = [replace(row, facets=facets_for(list_name, dict(row.cells))) for row in rows]
        links = {row.key: index.link(list_name, dict(row.cells), row.detail) for row in rows}
        await self._store.replace(list_name, rows, links)
        flat = [link for found in links.values() for link in found]
        return ListLoadReport(
            list_name=list_name,
            rows=len(rows),
            rows_with_links=sum(1 for found in links.values() if found),
            matched_links=sum(1 for link in flat if link.confidence == "matched"),
            possible_links=sum(1 for link in flat if link.confidence == "possible"),
        )
