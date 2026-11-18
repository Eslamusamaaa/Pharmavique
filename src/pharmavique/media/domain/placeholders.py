"""Stand-in pictures for drugs that have no picture on the web.

Many registry entries (hospital infusions, dialysis fluids, rare or local generics) are sold in no
online shop, so no real picture exists to find. For those the mapping offers a plain picture of
the drug's dosage form (a tablet, a bottle, a syringe...) and says so (`picture_kind` is
`placeholder`). It is never counted as a picture of the drug and never shown as its box.
"""

# order matters: the first group whose keyword appears in the dosage form wins
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("inhaler", ("inhal", "nasal", "spray", "nebul", "aerosol")),
    ("drops", ("eye drop", "ear drop", "drops", "ophthalmic")),
    ("injection", ("inject", "infusion", "dialysis", "haemodial", "vial", "ampoule", "implant")),
    ("suppository", ("suppositor", "pessar", "vaginal", "rectal", "enema")),
    ("topical", ("cream", "ointment", "gel", "lotion", "patch", "paste", "foam", "shampoo")),
    ("capsule", ("capsule",)),
    ("liquid", ("syrup", "suspension", "solution", "emulsion", "elixir", "liquid", "oral")),
    ("tablet", ("tablet", "caplet", "lozenge", "pastille", "granule", "powder", "sachet")),
)
_SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">'
)
_BACKGROUND = '<rect width="200" height="200" rx="24" fill="#f1f5f9"/>'
_INK = "#475569"
_ACCENT = "#0ea5e9"

_SHAPES: dict[str, str] = {
    "tablet": (
        f'<circle cx="100" cy="100" r="52" fill="#fff" stroke="{_INK}" stroke-width="6"/>'
        f'<line x1="56" y1="100" x2="144" y2="100" stroke="{_INK}" stroke-width="5"/>'
    ),
    "capsule": (
        f'<rect x="38" y="72" width="124" height="56" rx="28" fill="#fff" stroke="{_INK}" '
        f'stroke-width="6" transform="rotate(-30 100 100)"/>'
        f'<path d="M100 72 h-34 a28 28 0 0 0 0 56 h34z" fill="{_ACCENT}" stroke="{_INK}" '
        f'stroke-width="6" transform="rotate(-30 100 100)"/>'
    ),
    "liquid": (
        f'<rect x="72" y="56" width="56" height="96" rx="12" fill="#fff" stroke="{_INK}" '
        f'stroke-width="6"/><rect x="84" y="40" width="32" height="18" rx="4" fill="{_INK}"/>'
        f'<rect x="78" y="100" width="44" height="46" fill="{_ACCENT}"/>'
    ),
    "drops": (
        f'<path d="M100 40 C100 40 62 92 62 120 a38 38 0 0 0 76 0 C138 92 100 40 100 40z" '
        f'fill="{_ACCENT}" stroke="{_INK}" stroke-width="6"/>'
    ),
    "injection": (
        f'<rect x="64" y="84" width="84" height="32" rx="6" fill="#fff" stroke="{_INK}" '
        f'stroke-width="6" transform="rotate(-45 106 100)"/>'
        f'<line x1="52" y1="148" x2="76" y2="124" stroke="{_INK}" stroke-width="6"/>'
        f'<line x1="128" y1="60" x2="152" y2="36" stroke="{_INK}" stroke-width="6"/>'
    ),
    "topical": (
        f'<rect x="60" y="92" width="80" height="48" rx="6" fill="#fff" stroke="{_INK}" '
        f'stroke-width="6"/><path d="M60 92 l12 -24 h56 l12 24z" fill="{_ACCENT}" '
        f'stroke="{_INK}" stroke-width="6"/>'
    ),
    "inhaler": (
        f'<rect x="72" y="52" width="40" height="76" rx="8" fill="#fff" stroke="{_INK}" '
        f'stroke-width="6"/><rect x="72" y="112" width="84" height="32" rx="8" fill="{_ACCENT}" '
        f'stroke="{_INK}" stroke-width="6"/>'
    ),
    "suppository": (
        f'<path d="M60 100 q0 -34 40 -34 q40 0 40 34 q0 34 -40 34 q-40 0 -40 -34z" '
        f'fill="#fff" stroke="{_INK}" stroke-width="6"/>'
    ),
    "other": (
        f'<rect x="56" y="56" width="88" height="88" rx="14" fill="#fff" stroke="{_INK}" '
        f'stroke-width="6"/><path d="M100 76 v48 M76 100 h48" stroke="{_ACCENT}" '
        f'stroke-width="10" stroke-linecap="round"/>'
    ),
}
FORMS: tuple[str, ...] = tuple(_SHAPES)


def form_group(dosage_form: str | None) -> str:
    """The picture group for a registry dosage form ("other" when nothing fits)."""
    text = (dosage_form or "").lower()
    for group, keywords in _RULES:
        if any(keyword in text for keyword in keywords):
            return group
    return "other"


def placeholder_svg(group: str) -> str:
    return f"{_SVG_HEAD}{_BACKGROUND}{_SHAPES[group]}</svg>"


_CARD_NAME_LIMIT = 34  # characters of a name that fit on one line of the card
_CARD_NOTE = "Illustration - not a photo of the pack"


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def drug_card_svg(
    *,
    group: str,
    name_en: str,
    name_ar: str,
    strength: str,
    form: str,
    company: str,
) -> str:
    """A card for a drug that no shop shows: its dosage-form picture, its names, strength, form and
    company, and a line that says it is an illustration and not the pack. Shown by an app as a
    stand-in, never as the drug's box (`picture_kind` is `generated`)."""
    from xml.sax.saxutils import escape

    def line(y: int, size: int, weight: str, color: str, text: str, extra: str = "") -> str:
        if not text:
            return ""
        return (
            f'<text x="200" y="{y}" font-family="Segoe UI, Arial, sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="middle"{extra}>'
            f"{escape(text)}</text>"
        )

    details = " · ".join(part for part in (strength, form) if part)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">'
        '<rect width="400" height="400" rx="32" fill="#f1f5f9"/>'
        f'<g transform="translate(100 24)">{_SHAPES[group]}</g>'
        + line(250, 24, "700", "#0f172a", _short(name_en, _CARD_NAME_LIMIT))
        + line(284, 22, "600", "#0f172a", _short(name_ar, _CARD_NAME_LIMIT), ' direction="rtl"')
        + line(314, 17, "500", "#334155", _short(details, 44))
        + line(340, 15, "400", "#475569", _short(company, 44))
        + line(378, 12, "400", "#64748b", _CARD_NOTE)
        + "</svg>"
    )
