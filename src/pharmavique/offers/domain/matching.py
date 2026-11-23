"""Is this pharmacy listing the registered product? An all-conditions rule, never a score.

`matched` needs the same brand, the same ingredient set, the same strength of every ingredient
(after unit conversion), the same dosage form and the same pack size, each of them **known on both
sides**. A strength, form or ingredient that conflicts under the same brand is a `conflict`: it can
never become a match or a possible match, and it is remembered so the pair is not proposed again.
Anything unknown or a different pack size is `possible`. Two equally good candidates, or a listing
that contradicts itself, need a person (`needs_review`). Only medicines are compared with the
registry.

The ingredient names are keys made by the caller (salt words and spellings already resolved),
because that knowledge lives in another context and arrives through its contracts.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pharmavique.offers.domain.model import ListingCategory, MatchStatus
from pharmavique.offers.domain.quantity import Strength

__all__ = ["Assessment", "MatchDecision", "PackSize", "ProductFacts", "assess", "decide"]


@dataclass(frozen=True, slots=True)
class PackSize:
    count: int | None = None  # units in the pack: 30 tablets
    volume_ml: Decimal | None = None  # 100 ml


@dataclass(frozen=True, slots=True)
class ProductFacts:
    """What one side (a listing or a registry product) says about a product."""

    brand: str | None  # normalized core brand name, None when not known
    ingredients: frozenset[str]
    strengths: frozenset[Strength]
    form: str | None  # see `forms.dosage_form_key`
    pack: PackSize | None
    barcode: str | None = None
    contradicts_itself: bool = False  # a listing whose title and attributes disagree


@dataclass(frozen=True, slots=True)
class Assessment:
    outcome: str  # "matched", "possible", "conflict" or "different_product"
    verdicts: dict[str, str]  # field -> "same", "different" or "unknown"
    conflict_reason: str | None = None  # "ingredients", "strength" or "form"


@dataclass(frozen=True, slots=True)
class MatchDecision:
    status: MatchStatus
    register_number: str | None
    evidence: dict[str, Any] = field(default_factory=dict)
    conflicts: tuple[tuple[str, str], ...] = ()  # (register number, reason) never to be proposed


def _verdict(listing: object | None, registry: object | None) -> str:
    empty: tuple[object, ...] = (None, frozenset())
    if listing in empty or registry in empty:
        return "unknown"
    return "same" if listing == registry else "different"


def assess(listing: ProductFacts, registry: ProductFacts) -> Assessment:
    verdicts = {
        "brand": _verdict(listing.brand, registry.brand),
        "ingredients": _verdict(listing.ingredients, registry.ingredients),
        "strength": _verdict(listing.strengths, registry.strengths),
        "form": _verdict(listing.form, registry.form),
        "pack": _verdict(listing.pack, registry.pack),
    }
    if verdicts["brand"] == "different":
        return Assessment("different_product", verdicts)
    for name in ("ingredients", "strength", "form"):
        if verdicts[name] == "different":
            return Assessment("conflict", verdicts, name)
    if verdicts["brand"] == "unknown" and verdicts["ingredients"] != "same":
        return Assessment("different_product", verdicts)
    complete = all(
        verdicts[n] == "same" for n in ("brand", "ingredients", "strength", "form", "pack")
    )
    return Assessment("matched" if complete else "possible", verdicts)


def decide(
    category: ListingCategory,
    listing: ProductFacts,
    candidates: Sequence[tuple[str, ProductFacts]],
) -> MatchDecision:
    """The status of a listing among the registry candidates `(register number, facts)`."""
    if not category.eligible_for_registry_match:
        return MatchDecision(MatchStatus.NOT_APPLICABLE, None)
    matched: list[tuple[str, Assessment]] = []
    possible: list[tuple[str, Assessment]] = []
    conflicts: list[tuple[str, str]] = []
    for register_number, facts in candidates:
        found = assess(listing, facts)
        if found.outcome == "conflict":
            conflicts.append((register_number, found.conflict_reason or "unknown"))
        elif found.outcome == "matched":
            matched.append((register_number, found))
        elif found.outcome == "possible":
            possible.append((register_number, found))
    kept = tuple(conflicts)
    pool = matched or possible
    if not pool:
        return MatchDecision(MatchStatus.NO_MATCH, None, {}, kept)
    ambiguous = len(pool) > 1 or listing.contradicts_itself
    first_number, first = pool[0]
    evidence = {
        "verdicts": first.verdicts,
        "candidates": [number for number, _ in pool],
        "listing_contradicts_itself": listing.contradicts_itself,
    }
    if ambiguous:
        return MatchDecision(MatchStatus.NEEDS_REVIEW, None, evidence, kept)
    status = MatchStatus.MATCHED if matched else MatchStatus.POSSIBLE
    return MatchDecision(status, first_number, evidence, kept)
