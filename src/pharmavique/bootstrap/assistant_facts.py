"""`DrugFacts` for the assistant's tools, over the other contexts' published contracts.

Lives in the composition root because it reads four contexts at once (search, catalog,
substitution, knowledge). Values are plain JSON-ready dicts; every record keeps its source.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from pharmavique.catalog.contracts.queries import (
    CatalogDetails,
    CatalogQueries,
    ProductCard,
    ProductDetails,
)
from pharmavique.interactions.contracts.queries import (
    ContraindicationChecks,
    InteractionChecks,
    ProductIngredients,
)
from pharmavique.knowledge.application.retrieve import RetrievePassages
from pharmavique.search.contracts.queries import ProductSearch, SearchQuery
from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.text import arabic_skeleton, normalize_text
from pharmavique.substitution.contracts.queries import (
    EquivalenceQueries,
    IngredientFacts,
    ProductFacts,
)

CURRENCY_LABEL = {
    "owner_assumption": "ريال سعودي (افتراضي: العملة غير مذكورة في المصدر)",
    "source_stated": "ريال سعودي",
    "unconfirmed": "عملة غير مذكورة في المصدر",
}


def _price(details: ProductDetails) -> dict[str, Any] | None:
    price = details.price
    if price is None:
        return None
    amount: Decimal = price.amount.normalize()
    return {"amount": format(amount, "f"), "currency": CURRENCY_LABEL.get(price.currency_basis)}


def _details(d: ProductDetails) -> dict[str, Any]:
    card = d.card
    return {
        "register_number": card.register_number,
        "trade_name_ar": card.trade_name_ar,
        "trade_name_en": card.trade_name_en,
        "ingredients": [
            {"name": i.name, "strength": i.strength, "unit": i.unit} for i in d.ingredients
        ],
        "dosage_form": card.dosage_form_ar or card.dosage_form_en,
        "route": d.route_ar or d.route_en,
        "package": {"type": d.package_type, "size": d.package_size},
        "legal_status": d.legal_status,
        "distribution": d.distribution_site,
        "atc_codes": list(card.atc_codes),
        "shelf_life_as_stated": d.shelf_life,
        "storage": d.storage_ar or d.storage_en,
        "marketing_company": card.marketing_company,
        "manufacturers": [m.name for m in d.manufacturers],
        "marketing_status": card.marketing_status,
        "authorization_status": card.authorization_status,
        "listing_status": card.listing_status,
        "registered_price": _price(d),
        "source_ref": d.source_ref,
        "fetched_at": d.fetched_at.isoformat() if d.fetched_at else None,
    }


def _facts(d: ProductDetails) -> ProductFacts:
    return ProductFacts(
        d.card.register_number,
        tuple(IngredientFacts(i.name, i.strength, i.unit) for i in d.ingredients),
        d.card.dosage_form_en,
    )


def _name_match(query: str, card: ProductCard, exact: bool) -> str:
    """ "exact" when the search found the name exactly, or when every word typed starts a word of
    the product's own name (a shortened name: "Panadol 500" for "PANADOL 500 mg ..."). Anything
    else the forgiving search returned is a look-alike name, not the medicine asked for."""
    if exact:
        return "exact"
    typed = normalize_text(query).split()
    names = (card.trade_name_ar, card.trade_name_en)
    words = [word for name in names if name for word in normalize_text(name).split()]
    if typed and all(any(_same_word(word, part) for word in words) for part in typed):
        return "exact"
    return "similar_name_only"


def _same_word(word: str, typed: str) -> bool:
    """The typed word starts the product's word (a shortened name), or is another spelling of it:
    the same consonants in the same order, at least three of them ("بنادول" for "بانادول")."""
    if word.startswith(typed):
        return True
    skeleton = arabic_skeleton(typed)
    return len(skeleton) >= 3 and skeleton == arabic_skeleton(word)


class ContractDrugFacts:
    def __init__(
        self,
        search: ProductSearch,
        catalog: CatalogQueries,
        details: CatalogDetails,
        equivalence: EquivalenceQueries,
        passages: RetrievePassages,
        market: Market = Market.SA,
        interactions: InteractionChecks | None = None,
        contraindication_checks: ContraindicationChecks | None = None,
    ) -> None:
        self._search = search
        self._catalog = catalog
        self._details = details
        self._equivalence = equivalence
        self._passages = passages
        self._market = market
        self._interactions = interactions
        self._contraindications = contraindication_checks

    async def search_drugs(self, query: str, limit: int) -> list[dict[str, Any]]:
        result = await self._search.search(SearchQuery(query, self._market, limit, False))
        cards = await self._catalog.get_cards(
            self._market, [m.register_number for m in result.matches]
        )
        by_number = {c.register_number: c for c in cards}
        return [
            {
                "register_number": c.register_number,
                "trade_name_ar": c.trade_name_ar,
                "trade_name_en": c.trade_name_en,
                "ingredients": list(c.ingredient_names),
                "dosage_form": c.dosage_form_ar or c.dosage_form_en,
                "marketing_company": c.marketing_company,
                # the search is forgiving: a look-alike name is not the medicine that was asked for
                "name_match": _name_match(query, c, m.exact),
            }
            for m in result.matches
            if (c := by_number.get(m.register_number)) is not None
        ]

    async def drug_details(self, register_number: str) -> dict[str, Any] | None:
        found = await self._details.get_details(self._market, register_number.strip())
        return _details(found) if found else None

    async def same_ingredient(self, register_number: str, limit: int) -> list[dict[str, Any]]:
        base = await self._details.get_details(self._market, register_number.strip())
        if base is None:
            return []
        others = await self._details.same_ingredients(
            self._market, base.card.register_number, limit
        )
        verdicts = {
            c.product_id: c.verdict
            for c in self._equivalence.compare(_facts(base), [_facts(o) for o in others])
        }
        rows = []
        for other in others:
            row = _details(other)
            rows.append(
                {
                    "register_number": row["register_number"],
                    "trade_name_ar": row["trade_name_ar"],
                    "trade_name_en": row["trade_name_en"],
                    "ingredients": row["ingredients"],
                    "dosage_form": row["dosage_form"],
                    "marketing_company": row["marketing_company"],
                    "registered_price": row["registered_price"],
                    "verdict": verdicts.get(row["register_number"]),
                    "source_ref": row["source_ref"],
                }
            )
        return rows

    async def documents(
        self, query: str, register_numbers: Sequence[str], limit: int
    ) -> list[dict[str, Any]]:
        passages = await self._passages.search(query, register_numbers, limit)
        return [
            {
                "chunk_id": p.chunk_id,
                "list": p.list_name,
                "title": p.title,
                "text": p.text,
                "source_ref": p.source_ref,
                "published": p.published,
                "register_numbers": list(p.register_numbers),
                "read_by_ocr": p.ocr,
            }
            for p in passages
        ]

    async def check_interactions(self, register_numbers: Sequence[str]) -> list[dict[str, Any]]:
        if self._interactions is None:
            raise ValueError("the interaction source is not available")
        wanted = list(dict.fromkeys(r.strip() for r in register_numbers))
        cards = await self._catalog.get_cards(self._market, wanted)
        names = {c.register_number: c.trade_name_en or c.trade_name_ar or "" for c in cards}
        report = await self._interactions.run(
            [
                ProductIngredients(c.register_number, names[c.register_number], c.ingredient_names)
                for c in cards
            ]
        )
        rows: list[dict[str, Any]] = [
            {
                "kind": f.kind,
                "severity": f.severity,
                "drugs": [names.get(r, r) for r in f.registers],
                "registers": list(f.registers),
                "ingredients": list(f.ingredients),
                "source": f.source,
                "source_ref": "https://ddinter2.scbdd.com/" if f.source else None,
            }
            for f in report.findings
        ]
        rows.append(
            {
                "kind": "coverage",
                "checked_products": [names[c.register_number] for c in cards],
                "not_found_register_numbers": [r for r in wanted if r not in names],
                "not_covered": [
                    {"register_number": r, "ingredient": i} for r, i in report.unmatched
                ],
                "note": (
                    "A missing record is never a safety verdict: the source is incomplete and "
                    "ingredients listed here could not be judged at all."
                ),
            }
        )
        return rows

    async def contraindications(self, register_number: str) -> list[dict[str, Any]]:
        if self._contraindications is None:
            raise ValueError("the contraindication source is not available")
        cards = await self._catalog.get_cards(self._market, [register_number.strip()])
        if not cards:
            raise ValueError("no product with this register number")
        card = cards[0]
        report = await self._contraindications.run(
            [
                ProductIngredients(
                    card.register_number,
                    card.trade_name_en or card.trade_name_ar or "",
                    card.ingredient_names,
                )
            ]
        )
        rows: list[dict[str, Any]] = [
            {
                "register_number": item.register_number,
                "ingredient": item.ingredient,
                "disease": item.disease,
                "text": item.text,
                "source": item.source,
                "source_ref": "https://medic.renci.org/",
            }
            for item in report.items
        ]
        rows.append(
            {
                "kind": "coverage",
                "register_number": card.register_number,
                "note": (
                    "A missing record is never a clearance: the source covers only some "
                    "ingredients and only what drug labels state."
                ),
            }
        )
        return rows
