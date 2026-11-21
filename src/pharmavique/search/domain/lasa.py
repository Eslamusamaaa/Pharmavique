"""Look-alike sound-alike (LASA) brand names.

Two different brands whose names are spelled or sound alike can be mixed up by a person reading a
prescription or a shelf label. This module finds such pairs from the names alone. It is a warning
that says "a similar name exists, double-check", never a statement about the drugs themselves.
Thresholds are a first guess until a pharmacist reviews a sample (open question Q-26), so every
result is reported as unreviewed by the layers above.

Names are compared within one script: an Arabic name against Arabic names, a Latin name against
Latin names. Matching an Arabic spelling to its English transliteration is a separate problem.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from pharmavique.shared_kernel.text import normalize_text
from pharmavique.shared_kernel.trigrams import trigrams

SPELLED_ALIKE = 0.5  # trigram similarity at which two names look alike
HIGH_SPELLING = 0.7
MIN_KEY_LENGTH = 3
CLOSE_KEY_LENGTH = 6
SOUND_BACKING = 0.25
CLOSE_SOUND_BACKING = 0.4

_LATIN_REPLACEMENTS = (
    ("ph", "f"),
    ("ck", "k"),
    ("kh", "k"),
    ("gh", "g"),
    ("sh", "s"),
    ("ch", "k"),
    ("q", "k"),
    ("x", "ks"),
    ("z", "s"),
    ("y", "i"),
    ("w", "v"),
    ("b", "p"),
    ("d", "t"),
    ("g", "k"),
)
_SOFT_C = re.compile(r"c(?=[eiy])")
_LATIN_VOWELS = frozenset("aeiou")
_ARABIC_CLASSES = {
    "ث": "s", "س": "s", "ص": "s",
    "ز": "z", "ذ": "z", "ظ": "z",
    "ت": "t", "ط": "t", "د": "t", "ض": "t",
    "ك": "k", "ق": "k", "غ": "k", "ج": "k",
    "ب": "p", "ف": "f", "\u0647": "h", "ة": "h",
}  # fmt: skip
_ARABIC_VOWELS = frozenset("اأإآوىيءئؤ")


def _is_arabic(text: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in text)


def _collapse(text: str) -> str:
    out: list[str] = []
    for char in text:
        if not out or out[-1] != char:
            out.append(char)
    return "".join(out)


def _latin_key(word: str) -> str:
    text = _SOFT_C.sub("s", word).replace("c", "k")
    for old, new in _LATIN_REPLACEMENTS:
        text = text.replace(old, new)
    chars = [text[0]] if text else []
    chars += [c for c in text[1:] if c not in _LATIN_VOWELS and c.isalpha()]
    return _collapse("".join(chars))


def _arabic_key(word: str) -> str:
    chars = [_ARABIC_CLASSES.get(word[0], word[0])] if word else []
    for char in word[1:]:
        if char in _ARABIC_VOWELS:
            continue
        chars.append(_ARABIC_CLASSES.get(char, char))
    return _collapse("".join(chars))


def phonetic_key(name: str) -> str:
    """A rough sound key: similar-sounding spellings of one name share it.

    Vowels after the first letter are dropped and letters that sound close are merged, so
    "panadol" and "banadol", or "بنادول" and "بنادوول", give the same key.
    """
    words = normalize_text(name).split()
    return " ".join(
        _arabic_key(w) if _is_arabic(w) else _latin_key(w) for w in words if w and not w.isdigit()
    )


def _edit_distance_at_most_one(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _same_family(a: str, b: str) -> bool:
    """One name is the other plus whole words ("panadol" and "panadol extra"): same brand."""
    left, right = a.split(), b.split()
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return longer[: len(shorter)] == shorter


@dataclass(frozen=True, slots=True)
class LasaMatch:
    register_number: str
    brand: str
    score: float  # 0 to 1, for ordering only
    level: str  # "high" or "medium"
    reasons: tuple[str, ...]  # "sounds_alike" and/or "spelled_alike"


class LasaIndex:
    """Brand names (already reduced to the brand part) and who looks or sounds like whom."""

    def __init__(self, brands: Iterable[tuple[str, str]]) -> None:
        self._brand: dict[str, str] = {}
        self._script_groups: dict[bool, list[str]] = defaultdict(list)
        self._normalized: dict[str, str] = {}
        self._keys: dict[str, str] = {}
        self._trigrams: dict[str, frozenset[str]] = {}
        for register_number, brand in brands:
            text = normalize_text(brand)
            if not text:
                continue
            self._brand[register_number] = brand
            self._normalized[register_number] = text
            self._keys[register_number] = phonetic_key(text)
            self._trigrams[register_number] = trigrams(text)
            self._script_groups[_is_arabic(text)].append(register_number)

    def __len__(self) -> int:
        return len(self._brand)

    def similar_to(self, register_number: str, limit: int) -> tuple[LasaMatch, ...]:
        text = self._normalized.get(register_number)
        if text is None:
            return ()
        key = self._keys[register_number]
        mine = self._trigrams[register_number]
        found: dict[str, LasaMatch] = {}  # by normalized brand
        for other in self._script_groups[_is_arabic(text)]:
            other_text = self._normalized[other]
            if other == register_number or other_text == text or _same_family(text, other_text):
                continue  # the same brand, another strength or pack, is not a look-alike
            theirs = self._trigrams[other]
            score = len(mine & theirs) / len(mine | theirs) if mine and theirs else 0.0
            other_key = self._keys[other]
            same_sound = len(key) >= MIN_KEY_LENGTH and key == other_key
            close_sound = (
                len(key) >= CLOSE_KEY_LENGTH
                and key != other_key
                and _edit_distance_at_most_one(key, other_key)
            )
            # Sound alone finds too many pairs once vowels are dropped, so it must be backed by
            # some shared spelling: the name's first letter, or a share of its trigrams.
            sounds = (same_sound and (text[0] == other_text[0] or score >= SOUND_BACKING)) or (
                close_sound and score >= CLOSE_SOUND_BACKING
            )
            spelled = score >= SPELLED_ALIKE
            if not (sounds or spelled):
                continue
            reasons = tuple(
                r for r, ok in (("sounds_alike", sounds), ("spelled_alike", spelled)) if ok
            )
            level = "high" if (same_sound and sounds) or score >= HIGH_SPELLING else "medium"
            brand_key = other_text
            candidate = LasaMatch(
                register_number=other,
                brand=self._brand[other],
                score=max(score, 0.75 if same_sound and sounds else 0.55 if sounds else 0.0),
                level=level,
                reasons=reasons,
            )
            known = found.get(brand_key)  # one entry per brand: its other strengths are the same
            if known is None or (candidate.score, other) > (known.score, known.register_number):
                found[brand_key] = candidate
        ranked = sorted(found.values(), key=lambda m: (-m.score, m.brand, m.register_number))
        return tuple(ranked[:limit])
