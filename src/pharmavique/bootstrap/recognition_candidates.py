"""`CandidateFinder` for recognition over search and catalog contracts (composition root)."""

from pharmavique.catalog.contracts.queries import CatalogQueries
from pharmavique.recognition.domain.scans import MatchCandidate
from pharmavique.search.contracts.queries import ProductSearch, SearchQuery
from pharmavique.shared_kernel.market import Market


class SearchCandidateFinder:
    def __init__(
        self, search: ProductSearch, catalog: CatalogQueries, market: Market = Market.SA
    ) -> None:
        self._search = search
        self._catalog = catalog
        self._market = market

    async def find(self, query: str, limit: int) -> list[MatchCandidate]:
        result = await self._search.search(SearchQuery(query, self._market, limit, False))
        cards = await self._catalog.get_cards(
            self._market, [m.register_number for m in result.matches]
        )
        by_number = {card.register_number: card for card in cards}
        found = []
        for match in result.matches:
            card = by_number.get(match.register_number)
            if card is None:
                continue
            score = max((reason.score for reason in match.reasons), default=0.0)
            found.append(
                MatchCandidate(card.register_number, card.trade_name_ar, card.trade_name_en, score)
            )
        return found
