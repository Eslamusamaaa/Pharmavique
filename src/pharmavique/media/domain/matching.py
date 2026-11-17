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

# Words in a registry trade name that describe the form or the strength, not the brand. Shops do
# not put them in a page title, so they are dropped before matching and before searching.
_NAME_NOISE = frozenset(
    {
        "tab", "tabs", "tablet", "tablets", "caplet", "caplets", "cap", "caps", "capsule",
        "capsules", "syrup", "susp", "suspension", "supp", "suppository", "suppositories",
        "inj", "injection", "vial", "amp", "ampoule", "cream", "gel", "ointment", "drops",
        "drop", "oral", "film", "coated", "powder", "solution", "for", "per", "and", "with",
        "sachet", "sachets", "spray", "lotion", "infusion", "iv", "mg", "mcg", "g", "ml", "iu",
        "gm", "gms", "coted", "plastic", "single", "dose", "pack", "each",
        "اقراص", "قرص", "كبسول", "شراب", "معلق", "كريم", "مرهم", "لبوس", "حقن", "محلول", "للحقن",
        "ميكروجرام", "ميكرولتر", "مجم", "ملجم", "مل", "جم",
    }
)  # fmt: skip
# Whole words that are noise only as written (a lone "C" or "U" elsewhere may be part of a name)
_NAME_NOISE_RAW = frozenset({"f.c", "fc", "f.c.", "f.c.tablet", "u"})
# Pages that list many products (a brand, a category) are not the page of one drug, and their
# picture is usually the shop's own logo. Seen live on Saudi shops: "/collections/<brand>" and
# "/brands/<brand>" answering with the shop logo.
_LISTING_SEGMENTS = frozenset(
    {
        "collections", "collection", "brands", "brand", "category", "categories", "cat",
        "blog", "blogs", "pages", "search", "tag", "tags",
    }
)  # fmt: skip
# Words in a picture's address that show it belongs to the site, not to a product.
_SITE_ASSET_WORDS = (
    "logo", "og-image", "og_image", "placeholder", "no-image", "noimage", "no_image",
    "default-image", "shopby", "option_images", "banner", "favicon", "sprite", "splash",
)  # fmt: skip
# Arabic unit words on boxes and pages, read as the Latin units the registry uses
_ARABIC_UNITS = {
    "ملجم": "mg", "مجم": "mg", "ملغ": "mg", "ملغم": "mg", "ملجرام": "mg",
    "ميكروجرام": "mcg", "مل": "ml", "جم": "g", "جرام": "g", "غرام": "g",
}  # fmt: skip
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


def core_name(name: str | None) -> str:
    """The brand part of a registry trade name: form words, numbers and units are dropped.

    "AUGMENTIN 228 MG-5ML Powder for oral suspension" becomes "AUGMENTIN". A name made only of
    such words is kept as written.
    """
    raw = (name or "").strip()
    kept = [
        word
        for word in raw.split()
        if (normalized := normalize_text(word))
        and not any(char.isdigit() for char in normalized)
        and not set(normalized.split()) <= _NAME_NOISE
        and word.lower().strip("()[],") not in _NAME_NOISE_RAW
    ]
    return " ".join(kept) or raw


def brand_words(name: str | None) -> tuple[str, ...]:
    """The normalized words of the brand part of a registry name, without form or strength words.

    Empty when nothing but such words is left, because then the name says nothing about a brand.
    """
    return tuple(w for w in normalize_text(core_name(name)).split() if w not in _NAME_NOISE)


def build_queries(product: ProductRef) -> tuple[str, ...]:
    """Search phrases naming the drug and Saudi Arabia, in English and in Arabic."""
    queries: list[str] = []
    english = core_name(product.trade_name_en)
    if english:
        ingredient = product.ingredient_names[0] if product.ingredient_names else ""
        queries.append(" ".join(part for part in (english, ingredient, "Saudi Arabia") if part))
        queries.append(f"{english} Saudi Arabia")
    arabic = core_name(product.trade_name_ar)
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

    if is_listing_page(parsed.path):
        return MatchResult(MatchVerdict.REJECTED, 0.0, ("not_a_product_page",))
    if is_site_asset(candidate.image_url):
        return MatchResult(MatchVerdict.REJECTED, 0.0, ("site_asset",))

    signals: list[str] = []
    if _names_appear(product, text_tokens):
        signals.append("name")
    if _any_phrase_in(product.ingredient_names, text_tokens):
        signals.append("ingredient")
    if host.endswith(".sa") or text_tokens & _SAUDI_WORDS:
        signals.append("saudi")
    if _any_phrase_in((product.marketing_company or "",), text_tokens):
        signals.append("company")
    signals.extend(strength_signals(product, normalized))

    score = round(sum(_WEIGHTS.get(name, 0.0) for name in signals), 6)
    if "name" not in signals:
        verdict = MatchVerdict.REJECTED
    elif "strength_conflict" in signals or not ({"saudi", "company"} & set(signals)):
        verdict = MatchVerdict.NEEDS_REVIEW
    else:
        verdict = MatchVerdict.MATCHED
    return MatchResult(verdict=verdict, score=score, signals=tuple(signals))


def is_listing_page(path: str) -> bool:
    segments = {segment.lower() for segment in unquote(path).split("/") if segment}
    return bool(segments & _LISTING_SEGMENTS)


def is_site_asset(image_url: str) -> bool:
    address = unquote(urlparse(image_url).path).lower()
    return any(word in address for word in _SITE_ASSET_WORDS)


def strength_signals(product: ProductRef, normalized: str) -> list[str]:
    """`strength` when a registry strength is on the page; `strength_conflict` when the page
    states strengths and none of them is the registry's."""
    ours = [s for s in (normalize_text(strength) for strength in product.strengths) if s]
    if not ours:
        return []
    normalized = " ".join(_ARABIC_UNITS.get(word, word) for word in normalized.split())
    padded = f" {normalized} "
    if any(f" {strength} " in padded for strength in ours):
        return ["strength"]
    return ["strength_conflict"] if _STATED_STRENGTH.search(normalized) else []


def _names_appear(product: ProductRef, text_tokens: set[str]) -> bool:
    return _any_phrase_in(
        (core_name(product.trade_name_en), core_name(product.trade_name_ar)), text_tokens
    )


def _any_phrase_in(phrases: tuple[str, ...], text_tokens: set[str]) -> bool:
    """True when every word of at least one non-empty phrase is among the text's words."""
    for phrase in phrases:
        words = set(normalize_text(phrase).split())
        if words and words <= text_tokens:
            return True
    return False
