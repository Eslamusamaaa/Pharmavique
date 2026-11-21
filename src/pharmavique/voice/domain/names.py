"""The drug name inside a spoken request.

"أنا عايز بنادول" must search for "بنادول", not for the whole sentence. A language model does this
(see `ExtractDrugName`); this module is the fallback when it is unavailable and the check on what
it returns: it removes words that only say "I want / give me / the price of" and keeps the rest.
"""

import re
import unicodedata

MAX_NAME_CHARS = 60

# Words that carry no drug name: wishes, questions, politeness, the word "medicine" itself.
_FILLER = frozenset(
    [
        "انا",
        "أنا",
        "انت",
        "عايز",
        "عايزه",
        "عايزة",
        "عاوز",
        "عاوزه",
        "عاوزة",
        "اريد",
        "أريد",
        "ابغى",
        "أبغى",
        "ابي",
        "أبي",
        "بدي",
        "محتاج",
        "محتاجه",
        "محتاجة",
        "نفسي",
        "ممكن",
        "لو",
        "سمحت",
        "سمحتي",
        "من",
        "فضلك",
        "فضلكم",
        "هل",
        "فيه",
        "في",
        "عندكم",
        "عندك",
        "عندي",
        "موجود",
        "موجوده",
        "دواء",
        "دوا",
        "الدواء",
        "الدوا",
        "ادوية",
        "أدوية",
        "علاج",
        "العلاج",
        "حبوب",
        "حبايه",
        "حباية",
        "قرص",
        "اقراص",
        "أقراص",
        "ابحث",
        "ابحثلي",
        "دورلي",
        "دور",
        "لي",
        "ليا",
        "عن",
        "على",
        "علي",
        "ب",
        "بتاع",
        "بتاعي",
        "اسم",
        "اسمه",
        "اسمها",
        "ايه",
        "إيه",
        "ما",
        "هو",
        "هي",
        "ده",
        "دي",
        "كام",
        "سعر",
        "سعره",
        "اسعار",
        "أسعار",
        "بكام",
        "ثمن",
        "قيمة",
        "اعرف",
        "أعرف",
        "عايز",
        "اعرف",
        "i",
        "want",
        "need",
        "would",
        "like",
        "looking",
        "for",
        "a",
        "an",
        "the",
        "of",
        "me",
        "some",
        "please",
        "find",
        "search",
        "give",
        "show",
        "medicine",
        "drug",
        "tablet",
        "tablets",
        "pill",
        "pills",
        "price",
        "how",
        "much",
        "is",
        "there",
        "do",
        "you",
        "have",
    ]
)
_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u0640]")  # tashkeel and tatweel
_PUNCTUATION = re.compile(r"[\"'«»“”.,!?؟،؛:()\[\]{}…]+")


def _plain(word: str) -> str:
    return unicodedata.normalize("NFKC", _DIACRITICS.sub("", word)).casefold()


_FILLER_PLAIN = frozenset(_plain(word) for word in _FILLER)


def strip_filler(text: str) -> str:
    """The text without request words. Keeps everything else, in order (names, strengths)."""
    words = _PUNCTUATION.sub(" ", text).split()
    kept = [word for word in words if _plain(word) not in _FILLER_PLAIN]
    return " ".join(kept) if kept else " ".join(words)


def clean_model_name(answer: str) -> str | None:
    """A model's reply as a drug name, or None when it named nothing or rambled."""
    name = _PUNCTUATION.sub(" ", answer.strip().splitlines()[0] if answer.strip() else "").strip()
    name = " ".join(name.split())
    if not name or name.casefold() in {"none", "null", "no", "لا يوجد", "لا"}:
        return None
    if len(name) > MAX_NAME_CHARS or len(name.split()) > 6:
        return None
    return name
