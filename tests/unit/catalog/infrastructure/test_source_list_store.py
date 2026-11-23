"""Replacing a list must remove the old links by name, whether or not the database cascades."""

from collections.abc import Sequence
from types import TracebackType
from typing import Any

from sqlalchemy.dialects import postgresql

from pharmavique.catalog.application.list_loading import SourceListRow
from pharmavique.catalog.domain.list_linking import RowLink
from pharmavique.catalog.infrastructure.persistence.source_lists import SqlAlchemySourceListStore


class RecordingSession:
    def __init__(self, sink: list[str]) -> None:
        self.sink = sink

    async def __aenter__(self) -> "RecordingSession":
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def begin(self) -> "RecordingSession":
        return self

    async def execute(self, statement: Any, params: Any = None) -> None:
        self.sink.append(str(statement.compile(dialect=postgresql.dialect())).split("\n")[0])


async def test_old_links_are_deleted_by_list_name_before_the_new_ones_are_inserted() -> None:
    sink: list[str] = []
    store = SqlAlchemySourceListStore(lambda: RecordingSession(sink))  # type: ignore[arg-type]
    row = SourceListRow(
        key="K#1",
        entity_key="K",
        link=None,
        cells=(("Generic Name", "X"),),
        list_page=0,
        source="s",
        source_ref="r",
        snapshot_id="run",
        fetched_at=None,
        trust="official",
    )
    links: dict[str, Sequence[RowLink]] = {"K#1": [RowLink("1", "matched", "why")]}

    await store.replace("drug-shortage", [row], links)

    deleted = [line for line in sink if line.startswith("DELETE")]
    assert any("source_list_links" in line for line in deleted)
    assert any("source_list_rows" in line for line in deleted)
    first_insert = next(i for i, line in enumerate(sink) if line.startswith("INSERT"))
    assert all(sink.index(line) < first_insert for line in deleted)
