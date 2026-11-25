"""The look-alike names of every product, computed once a day and stored (daily refresh).

Building the name index on a fresh API instance took 2.6 s on Vercel (2026-11-25), and every new
instance paid it on its first similar-names answer. The daily refresh computes every product's
look-alikes after the catalog load; the API reads one row and builds the index itself only for a
product the last rebuild did not see.
"""

from collections.abc import Iterable

from pharmavique.search.application.ports import (
    NameSource,
    ProductNames,
    SimilarNameStore,
    StoredSimilarNames,
)
from pharmavique.search.domain.lasa import LasaIndex
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.names import core_name

WINDOW = 30  # look-alikes kept per product and script, before the weaker ones are set aside


def build_indexes(names: Iterable[ProductNames]) -> tuple[LasaIndex, LasaIndex]:
    """The English and the Arabic brand index. Many products share a trade name (other strengths
    and packs), so each name is reduced to its brand once."""
    brands: dict[str, str] = {}

    def brand(name: str) -> str:
        if name not in brands:
            brands[name] = core_name(name)
        return brands[name]

    english: list[tuple[str, str]] = []
    arabic: list[tuple[str, str]] = []
    for product in names:
        if product.en:
            english.append((product.register_number, brand(product.en)))
        if product.ar:
            arabic.append((product.register_number, brand(product.ar)))
    return LasaIndex(english), LasaIndex(arabic)


class RebuildSimilarNames:
    def __init__(self, source: NameSource, store: SimilarNameStore) -> None:
        self._source = source
        self._store = store

    async def rebuild(self, market: Market) -> int:
        """Compute and store every product's look-alikes; returns how many products were stored.
        A product with no look-alike is stored too, so the API knows it was computed."""
        names = await self._source.names(market)
        english, arabic = build_indexes(names)
        en, ar = english.similar_for_all(WINDOW), arabic.similar_for_all(WINDOW)
        rows = [
            StoredSimilarNames(
                p.register_number, en.get(p.register_number, ()), ar.get(p.register_number, ())
            )
            for p in names
        ]
        await self._store.replace(market, rows)
        return len(rows)
