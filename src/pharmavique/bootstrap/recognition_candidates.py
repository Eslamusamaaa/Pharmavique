"""`CandidateFinder` for recognition over search and catalog contracts (composition root)."""

import re
from decimal import Decimal, InvalidOperation

from pharmavique.catalog.contracts.queries import CatalogQueries, ProductCard
from pharmavique.recognition.domain.scans import MatchCandidate
from pharmavique.search.contracts.queries import ProductSearch, SearchQuery
from pharmavique.shared_kernel.market import Market

# The search ranks by name only, so every product of a brand ties ("Augmentin 1 g tablets" gave
# three suspensions). More are fetched, and the strength and form read on the box or prescription
# decide the order among them.
POOL = 25
_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mg|mcg|g|gm|ml|iu)?\b", re.IGNORECASE)
_TO_MG = {"mg": Decimal(1), "mcg": Decimal("0.001"), "g": Decimal(1000), "gm": Decimal(1000)}
_FORMS = (
    ("tablet", ("tab", "tabs", "tablet", "tablets", "caplet", "قرص", "أقراص", "اقراص")),
    ("capsule", ("cap", "caps", "capsule", "capsules", "كبسول", "كبسولة")),
    ("liquid", ("syrup", "suspension", "susp", "solution", "drops", "شراب", "معلق")),
    ("injection", ("inj", "injection", "vial", "ampoule", "amp", "infusion", "حقن")),
    ("topical", ("cream", "ointment", "gel", "lotion", "كريم", "مرهم")),
)


def _amounts(text: str) -> set[Decimal]:
    found: set[Decimal] = set()
    for number, unit in _AMOUNT.findall(text):
        try:
            value = Decimal(number.replace(",", "."))
        except InvalidOperation:
            continue
        found.add((value * _TO_MG.get(unit.lower(), Decimal(1))).normalize())
    return found


def _form(text: str) -> str | None:
    words = set(re.findall(r"[a-z؀-ۿ]+", text.lower()))
    return next((name for name, spelled in _FORMS if words & set(spelled)), None)


def _fit(query: str, card: ProductCard) -> float:
    """How well the strength and form read fit a product: a strength in its name that was read
    counts most, a strength in its name that was not read counts against it."""
    name = f"{card.trade_name_en or ''} {card.trade_name_ar or ''}"
    read, ours = _amounts(query), _amounts(name)
    fit = 0.0
    if read and ours:
        fit += 0.1 if read & ours else -0.1
    wanted, theirs = _form(query), _form(f"{name} {card.dosage_form_en or ''}")
    if wanted and theirs:
        fit += 0.08 if wanted == theirs else -0.08
    return fit


class SearchCandidateFinder:
    def __init__(
        self, search: ProductSearch, catalog: CatalogQueries, market: Market = Market.SA
    ) -> None:
        self._search = search
        self._catalog = catalog
        self._market = market

    async def find(self, query: str, limit: int) -> list[MatchCandidate]:
        result = await self._search.search(
            SearchQuery(query, self._market, max(limit, POOL), False)
        )
        cards = await self._catalog.get_cards(
            self._market, [m.register_number for m in result.matches]
        )
        by_number = {card.register_number: card for card in cards}
        ranked = []
        for position, match in enumerate(result.matches):
            card = by_number.get(match.register_number)
            if card is None:
                continue
            score = max((reason.score for reason in match.reasons), default=0.0)
            ranked.append((score + _fit(query, card), -position, card, score))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            MatchCandidate(card.register_number, card.trade_name_ar, card.trade_name_en, score)
            for _, _, card, score in ranked[:limit]
        ]
