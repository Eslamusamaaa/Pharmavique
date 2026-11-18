"""What `search` keeps about a product: the text it can be found by, already normalized.

`ProductToIndex` is search's own input type. The infrastructure adapter over the catalog's
published contract translates product cards into it, so nothing here knows the catalog.
"""

from dataclasses import dataclass

from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.names import core_name
from pharmavique.shared_kernel.text import normalize_text


@dataclass(frozen=True, slots=True)
class ProductKey:
    market: Market
    register_number: str


@dataclass(frozen=True, slots=True)
class ProductToIndex:
    key: ProductKey
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredient_names: tuple[str, ...]
    marketing_company: str | None
    withdrawn: bool


@dataclass(frozen=True, slots=True)
class SearchDocument:
    key: ProductKey
    names: tuple[str, ...]  # normalized trade names, English then Arabic, blanks left out
    ingredients: str  # normalized ingredient names, joined by a space
    company: str  # normalized marketing company, "" when unknown
    withdrawn: bool


def build_document(product: ProductToIndex) -> SearchDocument:
    names: list[str] = []
    for raw in (product.trade_name_en, product.trade_name_ar):
        full = normalize_text(raw or "")
        if full and full not in names:
            names.append(full)
    # The brand part is searched too: "GLUCOPHAGE 500 mg tablet" is found by "glucofage", which
    # the extra words would otherwise drown in a trigram comparison (recall@1 76% -> 96% on 300
    # generated misspellings of real names).
    for raw in (product.trade_name_en, product.trade_name_ar):
        brand = normalize_text(core_name(raw))
        if brand and brand not in names:
            names.append(brand)
    return SearchDocument(
        key=product.key,
        names=tuple(names),
        ingredients=normalize_text(" ".join(product.ingredient_names)),
        company=normalize_text(product.marketing_company or ""),
        withdrawn=product.withdrawn,
    )
