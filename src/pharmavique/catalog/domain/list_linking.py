"""Link rows of the official SFDA lists to catalog products.

The lists name drugs by text only, so every link carries how sure it is: `matched` (the evidence
agrees on name and substance, or on the company) or `possible` (needs a pharmacist or a person to
check). Nothing here claims two drugs are the same product when the evidence is thin.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pharmavique.shared_kernel.names import core_name
from pharmavique.shared_kernel.text import normalize_text

Confidence = Literal["matched", "possible"]

_SPLIT = re.compile(r"[,;+/]")
_MIN_TITLE_NAME = 6  # shorter ingredient names are too easy to find inside other words
# First words that name a salt or a class, not one substance: never enough to link on their own.
_SALT_WORDS = frozenset(
    {"sodium", "potassium", "calcium", "magnesium", "zinc", "iron", "vitamin", "hydrochloride"}
)


@dataclass(frozen=True, slots=True)
class RowLink:
    register_number: str
    confidence: Confidence
    reason: str


def _same_substance(left: str, right: str) -> bool:
    """Equal, or one is the other plus more words ("goserelin" and "goserelin acetate")."""
    return left == right or left.startswith(right + " ") or right.startswith(left + " ")


def _substances(text: str) -> tuple[str, ...]:
    parts = (normalize_text(part) for part in _SPLIT.split(text))
    return tuple(part for part in parts if part)


def _company_key(name: str) -> str:
    return normalize_text(name.split(" - ")[0])


# Words that name a legal form, not the company: dropped for the looser "core" comparison.
_LEGAL_WORDS = frozenset(
    {
        "llc", "ltd", "limited", "pvt", "private", "plc", "sa", "sl", "sas", "srl", "spa", "gmbh",
        "co", "company", "inc", "corp", "corporation", "ag", "ab", "bv", "nv", "as", "jsc", "kg",
        "lp", "llp", "pte", "sdn", "bhd", "the", "and",
    }
)  # fmt: skip
_PAREN = re.compile(r"\([^)]*\)")
_SITE = re.compile(r"[, ]+unit[ -]*[a-z0-9]+\b.*$")
_SIDE_OF_COUNTRY = re.compile(r"\s+-|-\s+")


def _company_core(name: str) -> str:
    """The company without legal form, site or country: "Granules India Limited Unit V" and
    "GRANULES INDIA LIMITED - INDIA" both become "granules india"."""
    head = _SIDE_OF_COUNTRY.split(name)[0]
    head = _PAREN.sub(" ", head).lower().replace(".", "")
    head = _SITE.sub("", head)
    words = [w for w in normalize_text(head).split() if w not in _LEGAL_WORDS]
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class LinkableProduct:
    register_number: str
    brand: str
    ingredients: tuple[str, ...]
    companies: frozenset[str]
    company_cores: frozenset[str] = frozenset()

    @classmethod
    def build(
        cls,
        register_number: str,
        trade_name: str,
        ingredients: Iterable[str],
        companies: Iterable[str] = (),
    ) -> "LinkableProduct":
        return cls(
            register_number=register_number,
            brand=normalize_text(core_name(trade_name)),
            ingredients=tuple(n for n in (normalize_text(i) for i in ingredients) if n),
            companies=frozenset(key for key in (_company_key(c) for c in companies) if key),
            company_cores=frozenset(core for core in (_company_core(c) for c in companies) if core),
        )

    def has_substances(self, wanted: tuple[str, ...]) -> bool:
        """The same set of substances: each one on both sides is matched by one on the other."""
        if not wanted or not self.ingredients:
            return False
        return all(any(_same_substance(w, i) for i in self.ingredients) for w in wanted) and all(
            any(_same_substance(w, i) for w in wanted) for i in self.ingredients
        )


class ProductLinkIndex:
    def __init__(self, products: Iterable[LinkableProduct]) -> None:
        self._by_brand: dict[str, list[LinkableProduct]] = defaultdict(list)
        self._by_first_word: dict[str, list[LinkableProduct]] = defaultdict(list)
        self._by_company: dict[str, list[LinkableProduct]] = defaultdict(list)
        self._by_company_core: dict[str, list[LinkableProduct]] = defaultdict(list)
        for item in products:
            if item.brand:
                self._by_brand[item.brand].append(item)
            for name in set(item.ingredients):
                self._by_first_word[name.split()[0]].append(item)
            for company in item.companies:
                self._by_company[company].append(item)
            for core in item.company_cores:
                self._by_company_core[core].append(item)

    def link(
        self,
        list_name: str,
        cells: Mapping[str, str],
        detail: Sequence[tuple[str, str]] = (),
    ) -> tuple[RowLink, ...]:
        if list_name in ("safety-labeling", "drug-approvals"):
            return self._by_brand_and_substance(cells)
        if list_name == "drug-shortage":
            brands = {
                normalize_text(core_name(value))
                for label, value in detail
                if label.lower() == "trade name" and value
            }
            return self._by_generic_name(cells.get("Generic Name", ""), brands)
        if list_name == "safety-alert":
            return self._by_title(cells.get("Title", ""))
        if list_name == "drug-companies":
            return self._by_company_name(cells.get("Company Name", ""))
        return ()

    def _by_brand_and_substance(self, cells: Mapping[str, str]) -> tuple[RowLink, ...]:
        brand = normalize_text(core_name(cells.get("Trade Name", "")))
        wanted = _substances(cells.get("Scientific Name", ""))
        links = []
        for item in self._by_brand.get(brand, []) if brand else []:
            if item.has_substances(wanted):
                links.append(RowLink(item.register_number, "matched", "brand and substance agree"))
            else:
                links.append(
                    RowLink(item.register_number, "possible", "same brand, substance differs")
                )
        return tuple(links)

    def _by_generic_name(
        self, generic: str, brands: set[str] | frozenset[str] = frozenset()
    ) -> tuple[RowLink, ...]:
        wanted = _substances(generic)
        if not wanted:
            return ()
        seen: dict[str, LinkableProduct] = {}
        for word in {w.split()[0] for w in wanted}:
            for item in self._by_first_word.get(word, []):
                seen[item.register_number] = item
        links = []
        for item in seen.values():
            if not item.has_substances(wanted):
                continue
            if item.brand and item.brand in brands:
                links.append(RowLink(item.register_number, "matched", "generic and trade name"))
            else:
                links.append(RowLink(item.register_number, "possible", "generic name only"))
        return tuple(links)

    def _by_title(self, title: str) -> tuple[RowLink, ...]:
        text = f" {normalize_text(title)} "
        words = set(text.split())
        found: dict[str, RowLink] = {}
        for word in words & self._by_first_word.keys():
            for item in self._by_first_word[word]:
                for name in item.ingredients:
                    head = name.split()[0]
                    named = f" {name} " in text or (
                        head == word and len(head) >= _MIN_TITLE_NAME and head not in _SALT_WORDS
                    )
                    if named:
                        found[item.register_number] = RowLink(
                            item.register_number, "possible", f"title names {head}"
                        )
        return tuple(found.values())

    def _by_company_name(self, company: str) -> tuple[RowLink, ...]:
        found: dict[str, RowLink] = {
            item.register_number: RowLink(item.register_number, "matched", "company name agrees")
            for item in self._by_company.get(_company_key(company), [])
        }
        core = _company_core(company)
        for item in self._by_company_core.get(core, []) if core else []:
            found.setdefault(
                item.register_number,
                RowLink(
                    item.register_number,
                    "possible",
                    "same company name once legal form and site are dropped",
                ),
            )
        return tuple(found.values())
