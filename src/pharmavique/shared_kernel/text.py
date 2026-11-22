"""Arabic and Latin text normalization for search. Pure functions, no framework.

The same function runs on the text we index and on the text a user types or an OCR engine reads, so
both sides land on one form. What it does, and why (spike 001 measured the damage without it:
a diacritic cut trigram similarity of one word to 0.118, an alef variant to 0.60):

- Unicode compatibility folding, case folding, and removal of every combining mark. That strips
  Arabic diacritics and also turns alef with hamza or madda into a bare alef, hamza on waw into
  waw and hamza on ya into ya; for Latin it drops accents.
- Alef wasla to alef, alef maqsura to ya, ta marbuta to ha, tatweel removed, Persian kaf and ya to
  the Arabic letters.
- Any decimal digit (Arabic-Indic, Persian, others) becomes an ASCII digit; the Arabic decimal
  separator becomes a dot.
- Everything that is not a letter or a digit becomes a space, except a dot between two digits.
- Letters and digits are separated ("paracetamol500mg" becomes "paracetamol 500 mg"), which helps
  with run-together OCR text.
"""

import unicodedata

_MAX_ROUNDS = 4  # normalization is applied until the text stops changing

_LETTER_MAP = str.maketrans(
    {
        "ٱ": "ا",  # alef wasla -> alef
        "ى": "ي",  # alef maqsura -> ya
        "ة": "ه",  # ta marbuta -> ha
        "ـ": None,  # tatweel
        "ک": "ك",  # Persian kaf -> kaf
        "ی": "ي",  # Persian ya -> ya
        "٫": ".",  # Arabic decimal separator
    }
)


def normalize_text(text: str) -> str:
    """Return the search form of `text` (see the module docstring). Idempotent."""
    current = text
    for _ in range(_MAX_ROUNDS):
        following = _normalize_once(current)
        if following == current:
            break
        current = following
    return current


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(normalize_text(text).split())


def _normalize_once(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    stripped = "".join(
        char for char in unicodedata.normalize("NFD", folded) if unicodedata.category(char) != "Mn"
    ).translate(_LETTER_MAP)

    pieces: list[str] = []
    previous = ""  # "a" letter, "d" digit, "" separator
    for index, char in enumerate(stripped):
        if char.isdecimal():
            kind, value = "d", str(unicodedata.decimal(char))
        elif char.isalpha():
            kind, value = "a", char
        elif char == "." and previous == "d" and _next_is_digit(stripped, index):
            pieces.append(".")
            continue
        else:
            kind, value = "", " "
        if kind and previous and kind != previous:
            pieces.append(" ")
        pieces.append(value)
        previous = kind
    return " ".join("".join(pieces).split())


def _next_is_digit(text: str, index: int) -> bool:
    return index + 1 < len(text) and text[index + 1].isdecimal()


_LONG_VOWEL_LETTERS = frozenset("اوي")  # alef, waw, ya
_ARABIC_BLOCK = ("؀", "ۿ")


def arabic_skeleton(word: str) -> str:
    """The consonants of an Arabic word, for telling two spellings of one transliterated name apart
    from two different names. Brand names are written in Arabic letters from another language and
    the long vowels (alef, waw, ya) are written in more than one way: the registry has "بانادول",
    people write "بنادول" or "بندول". The first letter stays (it may be a vowel letter), the other
    alef, waw and ya go, and a doubled letter counts once. A word with no Arabic letter, or one
    that would be left with fewer than two letters, is returned as it is. `word` is already
    normalized."""
    low, high = _ARABIC_BLOCK
    if not any(low <= char <= high for char in word):
        return word
    kept: list[str] = []
    for index, char in enumerate(word):
        if index and char in _LONG_VOWEL_LETTERS:
            continue
        if kept and kept[-1] == char:
            continue
        kept.append(char)
    return "".join(kept) if len(kept) >= 2 else word
