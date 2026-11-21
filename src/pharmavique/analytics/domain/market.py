"""The registry as a company sees it: who sells what, in which strengths and forms, at what price.

Everything here is computed from the official registry rows and says only what the registry says.
There are no sales or demand figures, so "few makers" is never "unmet demand". Prices are the
registered prices per pack as the source states them; packs differ, and a price range is only
formed among prices with the same currency and the same currency basis (never mixed).
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

NOT_STATED = "not stated"
THIN_AT = 2  # a strength-and-form with this many makers or fewer is called thin
MAX_MISSING = 100


@dataclass(frozen=True, slots=True)
class IngredientLine:
    name: str
    strength: str | None  # plain decimal text, as the source gives it
    unit: str | None


@dataclass(frozen=True, slots=True)
class MarketProduct:
    market: str
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredients: tuple[IngredientLine, ...]
    dosage_form: str | None
    marketing_company: str | None
    listing_status: str  # "listed" or "withdrawn"
    price_amount: Decimal | None
    price_currency_code: str | None
    price_currency_basis: str | None

    @property
    def listed(self) -> bool:
        return self.listing_status == "listed"

    @property
    def combination(self) -> tuple[str, ...]:
        """The sorted, upper-cased active ingredient names: the product's ingredient set."""
        return tuple(sorted({line.name.strip().upper() for line in self.ingredients}))

    @property
    def strength_key(self) -> str:
        """Each ingredient with its strength as stated, sorted, e.g. `PARACETAMOL 500 MG`."""
        parts = []
        for line in sorted(self.ingredients, key=lambda i: i.name.strip().upper()):
            amount = f"{line.strength} {line.unit or ''}".strip() if line.strength else NOT_STATED
            parts.append(f"{line.name.strip().upper()} {amount}")
        return " + ".join(parts) if parts else NOT_STATED

    @property
    def form_key(self) -> str:
        return (self.dosage_form or "").strip().upper() or NOT_STATED


def ingredient_key(name: str) -> str:
    return name.strip().upper()


@dataclass(frozen=True, slots=True)
class PriceRange:
    currency_code: str | None
    currency_basis: str
    count: int
    lowest: Decimal
    highest: Decimal


@dataclass(frozen=True, slots=True)
class Group:
    """Products with the same ingredient set (for example paracetamol alone, or with caffeine)."""

    ingredients: tuple[str, ...]
    listed: int
    withdrawn: int
    makers: int
    forms: tuple[tuple[str, int], ...]
    strengths: tuple[tuple[str, int], ...]
    price_ranges: tuple[PriceRange, ...]


@dataclass(frozen=True, slots=True)
class MarketMap:
    ingredient: str
    listed: int
    withdrawn: int
    makers: int
    top_makers: tuple[tuple[str, int], ...]
    groups: tuple[Group, ...]


def _price_ranges(products: Iterable[MarketProduct]) -> tuple[PriceRange, ...]:
    buckets: dict[tuple[str | None, str], list[Decimal]] = defaultdict(list)
    for product in products:
        if product.price_amount is not None:
            basis = product.price_currency_basis or "unconfirmed"
            buckets[(product.price_currency_code, basis)].append(product.price_amount)
    return tuple(
        PriceRange(code, basis, len(values), min(values), max(values))
        for (code, basis), values in sorted(
            buckets.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])
        )
    )


def _ranked(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def build_market_map(ingredient: str, products: Sequence[MarketProduct]) -> MarketMap:
    wanted = ingredient_key(ingredient)
    mine = [p for p in products if wanted in p.combination]
    by_combination: dict[tuple[str, ...], list[MarketProduct]] = defaultdict(list)
    for product in mine:
        by_combination[product.combination].append(product)

    groups = []
    for combination, rows in by_combination.items():
        listed = [p for p in rows if p.listed]
        groups.append(
            Group(
                ingredients=combination,
                listed=len(listed),
                withdrawn=len(rows) - len(listed),
                makers=len({p.marketing_company for p in listed if p.marketing_company}),
                forms=_ranked(Counter(p.form_key for p in listed)),
                strengths=_ranked(Counter(p.strength_key for p in listed)),
                price_ranges=_price_ranges(listed),
            )
        )
    groups.sort(key=lambda g: (-g.listed, g.ingredients))
    listed_all = [p for p in mine if p.listed]
    makers = Counter(p.marketing_company for p in listed_all if p.marketing_company)
    return MarketMap(
        ingredient=wanted,
        listed=len(listed_all),
        withdrawn=len(mine) - len(listed_all),
        makers=len(makers),
        top_makers=_ranked(Counter(makers))[:10],
        groups=tuple(groups),
    )


@dataclass(frozen=True, slots=True)
class GapCell:
    ingredients: tuple[str, ...]
    strength_key: str
    dosage_form: str
    products: int
    makers: int
    thin: bool


@dataclass(frozen=True, slots=True)
class MissingCell:
    """A strength and a form that both exist for this ingredient set but never together."""

    ingredients: tuple[str, ...]
    strength_key: str
    dosage_form: str


@dataclass(frozen=True, slots=True)
class Gaps:
    ingredient: str
    thin_at: int
    cells: tuple[GapCell, ...]  # fewest makers first
    missing: tuple[MissingCell, ...]


def find_gaps(ingredient: str, products: Sequence[MarketProduct], thin_at: int = THIN_AT) -> Gaps:
    wanted = ingredient_key(ingredient)
    listed = [p for p in products if p.listed and wanted in p.combination]
    cells: dict[tuple[tuple[str, ...], str, str], list[MarketProduct]] = defaultdict(list)
    for product in listed:
        cells[(product.combination, product.strength_key, product.form_key)].append(product)

    out = [
        GapCell(
            ingredients=combination,
            strength_key=strength,
            dosage_form=form,
            products=len(rows),
            makers=len({p.marketing_company for p in rows if p.marketing_company}),
            thin=len({p.marketing_company for p in rows if p.marketing_company}) <= thin_at,
        )
        for (combination, strength, form), rows in cells.items()
    ]
    out.sort(key=lambda c: (c.makers, c.products, c.ingredients, c.strength_key, c.dosage_form))

    missing: list[MissingCell] = []
    by_combination: dict[tuple[str, ...], tuple[set[str], set[str]]] = defaultdict(
        lambda: (set(), set())
    )
    for combination, strength, form in cells:
        strengths, forms = by_combination[combination]
        strengths.add(strength)
        forms.add(form)
    for combination, (strengths, forms) in sorted(by_combination.items()):
        for strength in sorted(strengths):
            for form in sorted(forms):
                if (combination, strength, form) not in cells and len(missing) < MAX_MISSING:
                    missing.append(MissingCell(combination, strength, form))
    return Gaps(ingredient=wanted, thin_at=thin_at, cells=tuple(out), missing=tuple(missing))
