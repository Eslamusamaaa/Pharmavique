"""A person's medicine history used as memory: compare a new drug with what they take now.

It joins three contexts without any of them knowing the others: the watchlist (what the person
takes now, their recorded allergies), the catalog (the products and their ingredients) and the
interaction data. A finding is a source's statement with the severity the source gives; nothing
here says to stop, switch or take a different dose, and "nothing found" is never "safe" because the
sources are incomplete. The comparison never leaves the server: no model sees a person's medicines.
"""

from dataclasses import dataclass
from uuid import UUID

from pharmavique.catalog.contracts.queries import CatalogQueries, ProductCard
from pharmavique.interactions.contracts.queries import InteractionChecks, ProductIngredients
from pharmavique.shared_kernel.market import Market
from pharmavique.watchlist.application.service import WatchlistService

MAX_COMPARED = 30  # the most recent current medicines a new drug is compared with


@dataclass(frozen=True, slots=True)
class HistoryFinding:
    kind: str  # "interaction" or "duplicate_ingredient"
    severity: str | None  # as the source rates it; None for a duplicate
    source: str | None
    with_register: str  # the medicine the person already takes
    with_name: str
    ingredients: tuple[str, str]  # the new drug's ingredient first, then the other's


@dataclass(frozen=True, slots=True)
class AllergyHit:
    allergy: str
    ingredient: str


@dataclass(frozen=True, slots=True)
class HistoryCheck:
    register_number: str
    name: str
    ingredients: tuple[str, ...]
    already_taken: bool  # the person already lists this medicine as current
    compared_with: tuple[tuple[str, str], ...]  # (register number, name) of each current medicine
    findings: tuple[HistoryFinding, ...]
    allergy_matches: tuple[AllergyHit, ...]
    unmatched: tuple[str, ...]  # ingredients of this drug the interaction source cannot judge


def _name(card: ProductCard) -> str:
    return card.trade_name_en or card.trade_name_ar or card.register_number


def _as_input(card: ProductCard) -> ProductIngredients:
    return ProductIngredients(card.register_number, _name(card), card.ingredient_names)


async def history_check(
    watchlist: WatchlistService,
    catalog: CatalogQueries,
    checks: InteractionChecks,
    user_id: UUID,
    register_number: str,
    market: Market = Market.SA,
) -> HistoryCheck | None:
    """None when the drug is not in the catalog."""
    found = await catalog.get_cards(market, [register_number])
    if not found:
        return None
    new = found[0]
    current = await watchlist.current_medicines(user_id)
    taken = new.register_number in {m.register_number for m in current}
    others = [m.register_number for m in current if m.register_number != new.register_number]
    others = others[:MAX_COMPARED]
    cards = {c.register_number: c for c in await catalog.get_cards(market, others)}
    compared = [cards[r] for r in others if r in cards]

    findings: list[HistoryFinding] = []
    unmatched: tuple[str, ...] = ()
    if compared:
        report = await checks.run([_as_input(new), *(_as_input(c) for c in compared)])
        for f in report.findings:
            if new.register_number not in f.registers:
                continue  # between two of the person's other medicines: not about this drug
            index = f.registers.index(new.register_number)
            other = f.registers[1 - index]
            other_card = cards.get(other)
            findings.append(
                HistoryFinding(
                    kind=f.kind,
                    severity=f.severity,
                    source=f.source,
                    with_register=other,
                    with_name=_name(other_card) if other_card else other,
                    ingredients=(f.ingredients[index], f.ingredients[1 - index]),
                )
            )
        unmatched = tuple(i for r, i in report.unmatched if r == new.register_number)

    allergies = await watchlist.check_allergies(user_id, new.ingredient_names)
    return HistoryCheck(
        register_number=new.register_number,
        name=_name(new),
        ingredients=new.ingredient_names,
        already_taken=taken,
        compared_with=tuple((c.register_number, _name(c)) for c in compared),
        findings=tuple(findings),
        allergy_matches=tuple(AllergyHit(a.allergy, a.ingredient) for a in allergies),
        unmatched=unmatched,
    )


@dataclass(frozen=True, slots=True)
class CurrentInteractions:
    medicines: tuple[tuple[str, str], ...]
    findings: tuple[tuple[HistoryFinding, str], ...]  # (finding, the register it is about)


async def current_interactions(
    watchlist: WatchlistService,
    catalog: CatalogQueries,
    checks: InteractionChecks,
    user_id: UUID,
    market: Market = Market.SA,
) -> CurrentInteractions:
    """Recorded interactions among the medicines the person takes now."""
    current = [m.register_number for m in await watchlist.current_medicines(user_id)]
    cards = {c.register_number: c for c in await catalog.get_cards(market, current[:MAX_COMPARED])}
    products = [cards[r] for r in current[:MAX_COMPARED] if r in cards]
    if len(products) < 2:
        return CurrentInteractions(tuple((c.register_number, _name(c)) for c in products), ())
    report = await checks.run([_as_input(c) for c in products])
    findings = []
    for f in report.findings:
        first, second = f.registers
        findings.append(
            (
                HistoryFinding(
                    kind=f.kind,
                    severity=f.severity,
                    source=f.source,
                    with_register=second,
                    with_name=_name(cards[second]) if second in cards else second,
                    ingredients=f.ingredients,
                ),
                first,
            )
        )
    return CurrentInteractions(
        tuple((c.register_number, _name(c)) for c in products), tuple(findings)
    )
