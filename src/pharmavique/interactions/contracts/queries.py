"""What other contexts may ask `interactions` (published language).

A finding is a statement from a source about a set of products, never advice: it carries the
source, the severity as the source rates it and the products involved. "Nothing found" is never
"safe": the sources are incomplete, so `complete` is always False.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProductIngredients:
    register_number: str
    name: str
    ingredients: tuple[str, ...]  # as the registry writes them


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str  # "interaction" or "duplicate_ingredient"
    severity: str | None  # "major", "moderate", "minor", "unknown"; None for a duplicate
    registers: tuple[str, str]
    ingredients: tuple[str, str]  # the registry's names, in the order of `registers`
    source: str | None  # None for a duplicate: it comes from our own registry data


@dataclass(frozen=True, slots=True)
class InteractionReport:
    findings: tuple[Finding, ...]
    unmatched: tuple[tuple[str, str], ...]  # (register number, ingredient) the source cannot judge
    complete: bool  # always False: absence of a finding is never a safety verdict


class InteractionChecks(Protocol):
    async def run(self, products: Sequence[ProductIngredients]) -> InteractionReport: ...


@dataclass(frozen=True, slots=True)
class Contraindication:
    register_number: str
    ingredient: str  # the registry's name of the ingredient
    disease: str  # the source's name of the condition
    text: str  # the label text the source took it from
    source: str


@dataclass(frozen=True, slots=True)
class ContraindicationReport:
    items: tuple[Contraindication, ...]
    complete: bool  # always False: a missing record is never a clearance


class ContraindicationChecks(Protocol):
    async def run(self, products: Sequence[ProductIngredients]) -> ContraindicationReport: ...
