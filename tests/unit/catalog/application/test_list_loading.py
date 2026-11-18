from collections.abc import Mapping, Sequence

from pharmavique.catalog.application.list_loading import LoadSourceList, SourceListRow
from pharmavique.catalog.domain.list_linking import LinkableProduct, RowLink


class FakeStore:
    def __init__(self) -> None:
        self.replaced: list[tuple[str, int, dict[str, int]]] = []

    async def linkable_products(self) -> list[LinkableProduct]:
        return [LinkableProduct.build("1", "TOPAMAX 25 MG", ("TOPIRAMATE",))]

    async def replace(
        self,
        list_name: str,
        rows: Sequence[SourceListRow],
        links: Mapping[str, Sequence[RowLink]],
    ) -> None:
        self.replaced.append((list_name, len(rows), {k: len(v) for k, v in links.items()}))


def row(key: str, **cells: str) -> SourceListRow:
    return SourceListRow(
        key=key,
        entity_key=key,
        link=None,
        cells=tuple((label.replace("_", " "), value) for label, value in cells.items()),
        list_page=0,
        source="sfda-list-x",
        source_ref="ref",
        snapshot_id="run",
        fetched_at=None,
        trust="official",
    )


async def test_rows_are_stored_and_the_report_counts_links_by_confidence() -> None:
    store = FakeStore()
    report = await LoadSourceList(store).run(
        "safety-labeling",
        [
            row("a", Trade_Name="Topamax", Scientific_Name="Topiramate"),
            row("b", Trade_Name="Unknown", Scientific_Name="Topiramate"),
        ],
    )
    assert store.replaced == [("safety-labeling", 2, {"a": 1, "b": 0})]
    assert (report.rows, report.rows_with_links) == (2, 1)
    assert (report.matched_links, report.possible_links) == (1, 0)
