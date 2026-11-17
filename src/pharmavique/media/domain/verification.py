"""Decide from the text printed on the picture whether it is the box of the registry drug.

The text comes from an OCR engine, so it is noisy: letters get swapped ("Panadoi"), symbols stick
to words ("BRUFEN@400"), and Arabic-only boxes come out as nothing useful. The rules are built for
that, and they never guess upward:

- `confirmed`: every word of the registry brand name, in English or in Arabic, is on the box (a
  long word may have a letter or two wrong) and the box does not state only a different strength;
- `strength_conflict`: the brand is there but the box states strengths and none is the registry's
  (for example "Glucophage XR 750 mg" for the registry's 500 mg tablet);
- `likely`: the brand is not readable but an ingredient and the registry strength are;
- `not_confirmed`: anything else, including a box whose text could not be read.

Only `confirmed` counts as verified. The others wait for a person.
"""

from dataclasses import dataclass
from enum import StrEnum

from pharmavique.media.domain.matching import ProductRef, brand_words, strength_signals
from pharmavique.shared_kernel.text import normalize_text
from pharmavique.shared_kernel.trigrams import similarity

_FUZZY_FROM = 6  # brand words at least this long may have OCR errors; shorter ones must match
_FUZZY_SCORE = 0.6
_CONTAINED_FROM = 5  # "glucophageø" contains "glucophage"


class PictureVerdict(StrEnum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    STRENGTH_CONFLICT = "strength_conflict"
    NOT_CONFIRMED = "not_confirmed"


@dataclass(frozen=True, slots=True)
class PictureCheck:
    verdict: PictureVerdict
    signals: tuple[str, ...]  # brand, brand_ar, ingredient, strength, strength_conflict, no_text


def verify_picture(product: ProductRef, ocr_text: str) -> PictureCheck:
    normalized = normalize_text(ocr_text)
    if not normalized:
        return PictureCheck(PictureVerdict.NOT_CONFIRMED, ("no_text",))
    tokens = normalized.split()

    signals: list[str] = []
    english = brand_words(product.trade_name_en)
    arabic = brand_words(product.trade_name_ar)
    if english and all(_word_on_box(word, tokens) for word in english):
        signals.append("brand")
    if arabic and all(_word_on_box(word, tokens) for word in arabic):
        signals.append("brand_ar")
    if any(_phrase_on_box(name, tokens) for name in product.ingredient_names):
        signals.append("ingredient")
    signals.extend(strength_signals(product, normalized))

    if "brand" in signals or "brand_ar" in signals:
        verdict = (
            PictureVerdict.STRENGTH_CONFLICT
            if "strength_conflict" in signals
            else PictureVerdict.CONFIRMED
        )
    elif "ingredient" in signals and "strength" in signals:
        verdict = PictureVerdict.LIKELY
    else:
        verdict = PictureVerdict.NOT_CONFIRMED
    return PictureCheck(verdict, tuple(signals))


def _word_on_box(word: str, tokens: list[str]) -> bool:
    for token in tokens:
        if token == word:
            return True
        if len(word) >= _CONTAINED_FROM and word in token:
            return True
        if len(word) >= _FUZZY_FROM and similarity(word, token) >= _FUZZY_SCORE:
            return True
    return False


def _phrase_on_box(phrase: str, tokens: list[str]) -> bool:
    words = normalize_text(phrase).split()
    return bool(words) and all(_word_on_box(word, tokens) for word in words)
