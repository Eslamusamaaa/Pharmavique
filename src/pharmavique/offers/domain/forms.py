"""Dosage forms as comparable keys.

"Film-coated tablet" and "Tablet" are one form, an orodispersible tablet is another, and an oral
solution is not a solution for injection.

A text that names no form gives None, which means "unknown", never "equal to anything".
"""

import re

__all__ = ["dosage_form_key"]

# The main form, first match wins. Parenteral forms (injection, infusion) are one.
_FORMS = (
    ("tablet", ("tablet", "tablets", "tab", "tabs", "caplet", "caplets")),
    ("capsule", ("capsule", "capsules", "cap", "caps", "softgel")),
    ("injection", ("injection", "inj", "injectable", "vial", "ampoule", "amp", "syringe",
                   "infusion", "pen", "cartridge")),
    ("inhaler", ("inhaler", "inhalation", "nebulizer", "nebuliser")),
    ("patch", ("patch", "patches")),
    ("suppository", ("suppository", "suppositories", "supp")),
    ("sachet", ("sachet", "sachets")),
    ("syrup", ("syrup",)),
    ("suspension", ("suspension", "susp")),
    ("cream", ("cream",)),
    ("ointment", ("ointment",)),
    ("gel", ("gel",)),
    ("lotion", ("lotion",)),
    ("drops", ("drops", "drop")),
    ("spray", ("spray",)),
    ("powder", ("powder", "lyophilisate", "lyophilized")),
    ("solution", ("solution", "sol", "soln", "liquid")),
)  # fmt: skip
# What changes how a form is taken or released: two products differing here are not the same.
_QUALIFIERS = {
    "orodispersible": "orodispersible", "dispersible": "dispersible", "chewable": "chewable",
    "effervescent": "effervescent", "sublingual": "sublingual",
    "modified": "modified", "prolonged": "modified", "extended": "modified",
    "delayed": "modified", "sustained": "modified", "enteric": "modified",
    "gastro": "modified", "resistant": "modified", "retard": "modified",
}  # fmt: skip
_WORDS = re.compile(r"[a-z]+")


def dosage_form_key(text: str | None) -> str | None:
    """`tablet`, `tablet:chewable`, `injection` and so on, or None when the text names no form."""
    tokens = set(_WORDS.findall((text or "").lower()))
    main = next((name for name, words in _FORMS if tokens & set(words)), None)
    if main is None:
        return None
    qualifiers = sorted({q for word, q in _QUALIFIERS.items() if word in tokens})
    return ":".join([main, *qualifiers])
