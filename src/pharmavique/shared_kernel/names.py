"""The brand part of a registry trade name.

SFDA writes names such as "AUGMENTIN 228 MG-5ML Powder for oral suspension" or "PANADOL EXTRA TAB".
Shops and users say "Augmentin" and "Panadol Extra", so matching, searching and picture lookups all
work from the brand part: form words, numbers and units are dropped. Shared by `search` and
`media`, which must not import each other.
"""

import re

from pharmavique.shared_kernel.text import normalize_text

# Words in a registry trade name that describe the form or the strength, not the brand. Shops do
# not put them in a page title, so they are dropped before matching and before searching.
NAME_NOISE = frozenset(
    {
        "tab", "tabs", "tablet", "tablets", "caplet", "caplets", "cap", "caps", "capsule",
        "capsules", "syrup", "susp", "suspension", "supp", "suppository", "suppositories",
        "inj", "injection", "vial", "amp", "ampoule", "cream", "gel", "ointment", "drops",
        "drop", "oral", "film", "coated", "powder", "solution", "for", "per", "and", "with",
        "sachet", "sachets", "spray", "lotion", "infusion", "iv", "mg", "mcg", "g", "ml", "iu",
        "gm", "gms", "coted", "plastic", "single", "dose", "pack", "each",
        "release", "modified", "prolonged", "extended", "chewable", "gastro", "resistant",
        "hard", "soft", "gelatin", "gelatine", "eye", "sol", "soln", "solu", "inf", "conc",
        "اقراص", "قرص", "كبسول", "شراب", "معلق", "كريم", "مرهم", "لبوس", "حقن", "محلول", "للحقن",
        "ميكروجرام", "ميكرولتر", "مجم", "ملجم", "مل", "جم",
    }
)  # fmt: skip
# Whole words that are noise only as written (a lone "C" or "U" elsewhere may be part of a name)
NAME_NOISE_RAW = frozenset({"f.c", "fc", "f.c.", "f.c.tablet", "u"})
# "F.C", "F-C" and "FC" (film coated) in any spelling, with or without a trailing form word
_FILM_COATED = re.compile(r"^f[.\-]?c(?:[.\-]?(?:tab|tabs|tablet|tablets|cap))?\.?$", re.IGNORECASE)


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
        and not set(normalized.split()) <= NAME_NOISE
        and word.lower().strip("()[],") not in NAME_NOISE_RAW
        and not _FILM_COATED.match(word.strip("()[],"))
    ]
    return " ".join(kept) or raw


def brand_words(name: str | None) -> tuple[str, ...]:
    """The normalized words of the brand part of a registry name, without form or strength words.

    Empty when nothing but such words is left, because then the name says nothing about a brand.
    """
    return tuple(w for w in normalize_text(core_name(name)).split() if w not in NAME_NOISE)
