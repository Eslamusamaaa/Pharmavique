"""Map a web image to a drug, simply, from the text around the picture.

A search result gives us the image URL, the page it sits on, the page or image title and the alt
text. This module judges whether that text is about our drug and whether it looks Saudi. It does
**not** look at the pixels, and it does not promise the picture shows the exact pack sold in a
Saudi pharmacy; it says "this page names this drug and shows signs of being Saudi". Reading the
box text with OCR can replace it later behind the same verdicts.

The rule is conservative on purpose, because the same brand name is sold in other countries as a
different product:

- `matched`: every word of the trade name appears, **and** there is Saudi evidence (a `.sa` domain,
  the word Saudi or its Arabic form, or the marketing company's name), **and** the page does not
  state a strength that contradicts the registry;
- `needs_review`: the name appears but nothing says Saudi, or the page states other strengths than
  the registry's, so a person looks;
- `rejected`: the name does not appear (words about the active ingredient alone are not enough).

A page that states no strength at all is neutral about it; one that states the registry's strength
scores higher.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import unquote, urlparse

from pharmavique.shared_kernel.market import Market
from pharmavique.shared_kernel.text import normalize_text

_SAUDI_WORDS = frozenset({"saudi", "ksa", "السعوديه", "سعودي", "سعوديه"})
_WEIGHTS = {"name": 0.4, "ingredient": 0.15, "saudi": 0.2, "company": 0.1, "strength": 0.15}
# "500 mg", "0.5 ml", "10 iu" after normalization (digits and letters are already separated)
_STATED_STRENGTH = re.compile(r"(?<!\S)\d+(?:\.\d+)? (?:mg|mcg|μg|g|ml|iu)(?!\S)")


class MatchVerdict(StrEnum):
    MATCHED = "matched"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ProductRef:
    """The drug we want a picture of: media's own input type, filled in by an adapter."""

    market: Market
    register_number: str
    trade_name_en: str | None
    trade_name_ar: str | None
    ingredient_names: tuple[str, ...]
    marketing_company: str | None
    strengths: tuple[str, ...] = ()  # as the registry states them, for example "500 mg"


@dataclass(frozen=True, slots=True)
class ImageCandidate:
    """One image found by a web search, with the text around it."""

    image_url: str
    page_url: str
    title: str
    alt_text: str
    page_text: str = ""  # description, headings and other visible text of the page, when read


@dataclass(frozen=True, slots=True)
class MatchResult:
    verdict: MatchVerdict
    score: float  # 0 to 1, from the signals that fired
    signals: tuple[str, ...]  # which of name, ingredient, saudi, company, strength fired


def build_queries(product: ProductRef) -> tuple[str, ...]:
    """Search phrases naming the drug and Saudi Arabia, in English and in Arabic."""
    queries: list[str] = []
    english = (product.trade_name_en or "").strip()
    if english:
        ingredient = product.ingredient_names[0] if product.ingredient_names else ""
        queries.append(" ".join(part for part in (english, ingredient, "Saudi Arabia") if part))
        queries.append(f"{english} Saudi Arabia")
    arabic = (product.trade_name_ar or "").strip()
    if arabic:
        queries.append(f"{arabic} السعودية")
    return tuple(dict.fromkeys(queries))


def judge(product: ProductRef, candidate: ImageCandidate) -> MatchResult:
    parsed = urlparse(candidate.page_url)
    host = (parsed.hostname or "").lower()
    # The address path counts as page text (shops put the product name in it); the host does not,
    # so a site called after the drug is not mistaken for a page about it.
    normalized = normalize_text(
        f"{candidate.title} {candidate.alt_text} {unquote(parsed.path)} {candidate.page_text}"
    )
    text_tokens = set(normalized.split())

    signals: list[str] = []
    if _names_appear(product, text_tokens):
        signals.append("name")
    if _any_phrase_in(product.ingredient_names, text_tokens):
        signals.append("ingredient")
    if host.endswith(".sa") or text_tokens & _SAUDI_WORDS:
        signals.append("saudi")
    if _any_phrase_in((product.marketing_company or "",), text_tokens):
        signals.append("company")
    signals.extend(_strength_signals(product, normalized))

    score = round(sum(_WEIGHTS.get(name, 0.0) for name in signals), 6)
    if "name" not in signals:
        verdict = MatchVerdict.REJECTED
    elif "strength_conflict" in signals or not ({"saudi", "company"} & set(signals)):
        verdict = MatchVerdict.NEEDS_REVIEW
    else:
        verdict = MatchVerdict.MATCHED
    return MatchResult(verdict=verdict, score=score, signals=tuple(signals))


def _strength_signals(product: ProductRef, normalized: str) -> list[str]:
    """`strength` when a registry strength is on the page; `strength_conflict` when the page
    states strengths and none of them is the registry's."""
    ours = [s for s in (normalize_text(strength) for strength in product.strengths) if s]
    if not ours:
        return []
    padded = f" {normalized} "
    if any(f" {strength} " in padded for strength in ours):
        return ["strength"]
    return ["strength_conflict"] if _STATED_STRENGTH.search(normalized) else []


def _names_appear(product: ProductRef, text_tokens: set[str]) -> bool:
    return _any_phrase_in((product.trade_name_en or "", product.trade_name_ar or ""), text_tokens)


def _any_phrase_in(phrases: tuple[str, ...], text_tokens: set[str]) -> bool:
    """True when every word of at least one non-empty phrase is among the text's words."""
    for phrase in phrases:
        words = set(normalize_text(phrase).split())
        if words and words <= text_tokens:
            return True
    return False
