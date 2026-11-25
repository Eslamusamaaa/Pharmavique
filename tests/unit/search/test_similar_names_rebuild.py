"""The daily rebuild of every product's look-alike names."""

from collections.abc import Sequence

from pharmavique.search.application.ports import ProductNames, StoredSimilarNames
from pharmavique.search.application.similar_names import WINDOW, RebuildSimilarNames, build_indexes
from pharmavique.shared_kernel.market import Market

NAMES = [
    ProductNames("1", "PANADOL 500 MG TABLET", "بنادول"),
    ProductNames("2", "PANADOLE 250 MG TAB", "بنادوول"),
    ProductNames("3", "AUGMENTIN 625 MG TAB", None),
    ProductNames("4", None, None),
]


class Source:
    async def names(self, market: Market) -> Sequence[ProductNames]:
        return NAMES


class Store:
    def __init__(self) -> None:
        self.saved: dict[Market, list[StoredSimilarNames]] = {}

    async def replace(self, market: Market, rows: Sequence[StoredSimilarNames]) -> None:
        self.saved[market] = list(rows)

    async def find(self, market: Market, register_number: str) -> StoredSimilarNames | None:
        return next(
            (r for r in self.saved.get(market, []) if r.register_number == register_number), None
        )


async def test_every_product_is_stored_with_what_the_index_would_answer() -> None:
    store = Store()

    count = await RebuildSimilarNames(Source(), store).rebuild(Market.SA)

    english, arabic = build_indexes(NAMES)
    assert count == 4
    rows = {r.register_number: r for r in store.saved[Market.SA]}
    for number in ("1", "2", "3", "4"):
        assert rows[number].english == english.similar_to(number, WINDOW)
        assert rows[number].arabic == arabic.similar_to(number, WINDOW)
    assert [m.register_number for m in rows["1"].english] == ["2"]
    assert [m.register_number for m in rows["1"].arabic] == ["2"]
    # computed, with nothing found: stored empty, so the API does not build the index for it
    assert rows["3"].english == ()
    assert rows["4"].english == ()
