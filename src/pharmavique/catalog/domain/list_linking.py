"""Link rows of the official SFDA lists to catalog products.

The lists name drugs by text only, so every link carries how sure it is: `matched` (the evidence
agrees on name and substance, or on the company) or `possible` (needs a pharmacist or a person to
check). Nothing here claims two drugs are the same product when the evidence is thin.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pharmavique.shared_kernel.names import core_name
from pharmavique.shared_kernel.text import normalize_text

Confidence = Literal["matched", "possible"]

_SPLIT = re.compile(r"[,;+/]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_REGISTER_TOKEN = re.compile(r"(?<![0-9-])[0-9]{10}(?![0-9-])")  # registered drugs have 10 digits
_MIN_TITLE_NAME = 6  # shorter ingredient names are too easy to find inside other words
# First words that name a salt or a class, not one substance: never enough to link on their own.
_SALT_WORDS = frozenset(
    {"sodium", "potassium", "calcium", "magnesium", "zinc", "iron", "vitamin", "hydrochloride"}
)


@dataclass(frozen=True, slots=True)
class RowLink:
    register_number: str
    confidence: Confidence
    reason: str


def _number_list(text: str) -> tuple[str, ...]:
    """Every number written, repeats kept ("5 mg/5 mg" gives ("5", "5"))."""
    return tuple(n.replace(",", ".") for n in _NUMBER.findall(normalize_text(text)))


def _numbers(trade_name: str) -> frozenset[str]:
    """The numbers written in a trade name ("ESOMA 20 MG" gives {"20"}): its strength and pack."""
    return frozenset(_number_list(trade_name))


_PACK_COUNT = re.compile(r"(?<![\d.])(\d+)\s*'?s\b", re.IGNORECASE)  # "(28S)", "56 S", "14's"
_VOLUME = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*ml\b", re.IGNORECASE)  # "(10ml)", "500 ml"


# "250 mcg/2 ml" is per 2 ml, "250 mcg/ml" per 1 ml: the volume after a slash.
_PER_VOLUME = re.compile(r"/\s*(\d+(?:\.\d+)?)?\s*ml\b", re.IGNORECASE)
# An amount with a mass or unit after it: how many strengths a name writes.
_UNIT_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*(?:mg|mcg|µg|g|gm|iu|i\.u)\b", re.IGNORECASE)


def _per_volume(text: str) -> frozenset[str]:
    return frozenset(m.group(1) or "1" for m in _PER_VOLUME.finditer(text))


def _strength_count(text: str) -> int:
    return len(_UNIT_AMOUNT.findall(text))


def _pack(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """(pack counts, volumes) a name writes. A volume after a slash is a concentration
    ("250 mcg/2 ml"), not the size of the pack, so it is left out."""
    plain = text.replace("\xa0", " ")
    counts = frozenset(m.group(1) for m in _PACK_COUNT.finditer(plain))
    volumes = frozenset(
        m.group(1) for m in _VOLUME.finditer(plain) if not plain[: m.start()].rstrip().endswith("/")
    )
    return counts, volumes


# Words after a brand that describe the form, not another product ("esoma delayed release").
# Any other extra word ("plus", "paediatric", "forte") names a different product.
_DESCRIPTIVE = frozenset(
    {
        "delayed", "release", "modified", "prolonged", "extended", "chewable", "orodispersible",
        "dispersible", "effervescent", "sublingual", "enteric", "gastro", "resistant", "coated",
        "film", "oral",
    }
)  # fmt: skip
# The main form of a product, first match wins. Parenteral forms (injection, infusion) are one.
_FORMS = (
    ("tablet", ("tablet", "tablets", "tab", "tabs", "caplet", "caplets")),
    ("capsule", ("capsule", "capsules", "cap", "caps", "softgel")),
    ("injection", ("injection", "inj", "injectable", "vial", "ampoule", "amp", "syringe",
                   "infusion", "pen", "cartridge")),
    ("inhaler", ("inhaler", "inhalation", "nebulizer")),
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


def _form_of(text: str) -> tuple[str | None, frozenset[str]]:
    """(main form, qualifiers) a name or dosage form writes; (None, empty) when it names none."""
    tokens = set(normalize_text(text).split())
    main = next((name for name, words in _FORMS if tokens & set(words)), None)
    return main, frozenset(q for word, q in _QUALIFIERS.items() if word in tokens)


@dataclass(frozen=True, slots=True)
class ListedName:
    """One trade name as a shortage row lists it, with what it says about strength and form."""

    numbers: frozenset[str]
    form: str | None
    qualifiers: frozenset[str]
    number_list: tuple[str, ...] = ()  # every number, repeats kept: "10 mg/5 mg" is not "5 mg/5 mg"
    pack_counts: frozenset[str] = frozenset()
    volumes: frozenset[str] = frozenset()
    per_volume: frozenset[str] = frozenset()  # "250 mcg/2 ml" gives {"2"}
    strength_count: int = (
        0  # amounts with a unit: a starter pack writes more than one per substance
    )


def _listed_name(value: str) -> ListedName:
    form, qualifiers = _form_of(value)
    counts, volumes = _pack(value)
    return ListedName(
        _numbers(value),
        form,
        qualifiers,
        _number_list(value),
        counts,
        volumes,
        _per_volume(value),
        _strength_count(value),
    )


def _covers(listed: tuple[str, ...], ours: tuple[str, ...]) -> bool:
    """Each of our strengths is written in the listed name, as many times as we have it."""
    have = Counter(listed)
    return all(have[number] >= count for number, count in Counter(ours).items())


def _verdict(listed: ListedName, item: "LinkableProduct") -> str:
    """One of "confirmed", "unconfirmed" (nothing against it, not enough to say) or "conflict"."""
    if listed.form and item.form:
        if listed.form != item.form:
            return "conflict"
        # A release profile ("modified") is compared only against a registered dosage form: a
        # product with no dosage form on record cannot be said to be immediate release.
        wanted = listed.qualifiers if item.has_dosage_form else listed.qualifiers - {"modified"}
        ours = item.qualifiers if item.has_dosage_form else item.qualifiers - {"modified"}
        if wanted != ours:
            return "conflict"
    # A different pack (14 or 28 capsules, a 10 or 20 ml vial) is another registration.
    if listed.pack_counts and item.pack_counts and not listed.pack_counts & item.pack_counts:
        return "conflict"
    if listed.volumes and item.volumes and not listed.volumes & item.volumes:
        return "conflict"
    # Another concentration ("250 mcg/2 ml" is not "250 mcg/ml").
    if listed.per_volume and item.per_volume and not listed.per_volume & item.per_volume:
        return "conflict"
    # More strengths than the product has substances: a starter pack ("0.5 mg 11 tablets + 1 mg
    # 14 tablets"), another registration than a single-strength product.
    if listed.strength_count > max(1, len(item.ingredients)):
        return "conflict"
    if listed.numbers and item.strength_list:
        return "confirmed" if _covers(listed.number_list, item.strength_list) else "conflict"
    mine = item.name_numbers
    if listed.numbers and mine:
        return "confirmed" if mine <= listed.numbers else "conflict"
    return "unconfirmed"


def _brand_related(listed: str, ours: str) -> bool:
    """The same brand, or the listed name is ours plus words that only describe the form
    ("esoma delayed release" for "esoma").

    Never the other way round, and never a word that names another product: a shortage of
    "Panadol" says nothing about "Panadol Advance", and "Singulair Paediatric" is not
    "Singulair"."""
    if listed == ours:
        return True
    if not listed.startswith(ours + " "):
        return False
    return set(listed[len(ours) :].split()) <= _DESCRIPTIVE


def _same_substance(left: str, right: str) -> bool:
    """Equal, or one is the other plus more words ("goserelin" and "goserelin acetate")."""
    return left == right or left.startswith(right + " ") or right.startswith(left + " ")


def _substances(text: str) -> tuple[str, ...]:
    parts = (normalize_text(part) for part in _SPLIT.split(text))
    return tuple(part for part in parts if part)


def _company_key(name: str) -> str:
    return normalize_text(name.split(" - ")[0])


# Words that name a legal form, not the company: dropped for the looser "core" comparison.
_LEGAL_WORDS = frozenset(
    {
        "llc", "ltd", "limited", "pvt", "private", "plc", "sa", "sl", "sas", "srl", "spa", "gmbh",
        "co", "company", "inc", "corp", "corporation", "ag", "ab", "bv", "nv", "as", "jsc", "kg",
        "lp", "llp", "pte", "sdn", "bhd", "the", "and",
    }
)  # fmt: skip
_PAREN = re.compile(r"\([^)]*\)")
_SITE = re.compile(r"[, ]+unit[ -]*[a-z0-9]+\b.*$")
_SIDE_OF_COUNTRY = re.compile(r"\s+-|-\s+")


def _company_core(name: str) -> str:
    """The company without legal form, site or country: "Granules India Limited Unit V" and
    "GRANULES INDIA LIMITED - INDIA" both become "granules india"."""
    head = _SIDE_OF_COUNTRY.split(name)[0]
    head = _PAREN.sub(" ", head).lower().replace(".", "")
    head = _SITE.sub("", head)
    words = [w for w in normalize_text(head).split() if w not in _LEGAL_WORDS]
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class LinkableProduct:
    register_number: str
    brand: str
    ingredients: tuple[str, ...]
    companies: frozenset[str]
    company_cores: frozenset[str] = frozenset()
    name_numbers: frozenset[str] = frozenset()  # numbers in the full trade name (strength, pack)
    strengths: frozenset[str] = frozenset()  # the registry's strength of each ingredient
    form: str | None = None  # main dosage form from the registry (and the name)
    qualifiers: frozenset[str] = frozenset()
    has_dosage_form: bool = False  # the registry states a dosage form
    strength_list: tuple[str, ...] = ()  # the registry's strengths, repeats kept ("5", "5")
    pack_counts: frozenset[str] = frozenset()  # pack counts the trade name writes ("28S")
    volumes: frozenset[str] = frozenset()  # pack volumes the trade name writes ("10ml")
    per_volume: frozenset[str] = frozenset()  # "250 mcg/ml" gives {"1"}

    @classmethod
    def build(
        cls,
        register_number: str,
        trade_name: str,
        ingredients: Iterable[str],
        companies: Iterable[str] = (),
        strengths: Iterable[str] = (),
        dosage_form: str = "",
    ) -> "LinkableProduct":
        form, qualifiers = _form_of(f"{dosage_form} {trade_name}")
        counts, volumes = _pack(trade_name)
        strength_list = _number_list(" ".join(strengths))
        return cls(
            register_number=register_number,
            brand=normalize_text(core_name(trade_name)),
            ingredients=tuple(n for n in (normalize_text(i) for i in ingredients) if n),
            companies=frozenset(key for key in (_company_key(c) for c in companies) if key),
            company_cores=frozenset(core for core in (_company_core(c) for c in companies) if core),
            name_numbers=_numbers(trade_name),
            strengths=_numbers(" ".join(strengths)),
            form=form,
            qualifiers=qualifiers,
            has_dosage_form=bool(dosage_form.strip()),
            strength_list=strength_list,
            pack_counts=counts,
            volumes=volumes,
            per_volume=_per_volume(trade_name),
        )

    @property
    def generic_named(self) -> bool:
        """The product is named after its substance ("DEXTROSE 5%"): a list row that names only
        the substance cannot say which maker's product it means."""
        words = set(self.brand.split())
        return bool(words) and any(words <= set(i.split()) for i in self.ingredients)

    def has_substances(self, wanted: tuple[str, ...]) -> bool:
        """The same set of substances: each one on both sides is matched by one on the other."""
        if not wanted or not self.ingredients:
            return False
        return all(any(_same_substance(w, i) for i in self.ingredients) for w in wanted) and all(
            any(_same_substance(w, i) for w in wanted) for i in self.ingredients
        )


def _names_ingredient(name: str, text: str, words: set[str]) -> bool:
    """The padded, normalized text names this ingredient: in full, or by a first word that is long
    enough and not a salt or class word."""
    head = name.split()[0]
    return f" {name} " in text or (
        head in words and len(head) >= _MIN_TITLE_NAME and head not in _SALT_WORDS
    )


class ProductLinkIndex:
    def __init__(self, products: Iterable[LinkableProduct]) -> None:
        self._by_register: dict[str, list[LinkableProduct]] = defaultdict(list)
        self._by_brand: dict[str, list[LinkableProduct]] = defaultdict(list)
        self._by_first_word: dict[str, list[LinkableProduct]] = defaultdict(list)
        self._by_company: dict[str, list[LinkableProduct]] = defaultdict(list)
        self._by_company_core: dict[str, list[LinkableProduct]] = defaultdict(list)
        for item in products:
            self._by_register[item.register_number].append(item)
            if item.brand:
                self._by_brand[item.brand].append(item)

            for name in set(item.ingredients):
                self._by_first_word[name.split()[0]].append(item)
            for company in item.companies:
                self._by_company[company].append(item)
            for core in item.company_cores:
                self._by_company_core[core].append(item)

    def link(
        self,
        list_name: str,
        cells: Mapping[str, str],
        detail: Sequence[tuple[str, str]] = (),
    ) -> tuple[RowLink, ...]:
        if list_name in ("safety-labeling", "drug-approvals"):
            return self._by_brand_and_substance(cells)
        if list_name == "rmm":
            return self._by_brand_and_substance(
                {
                    "Trade Name": cells.get("Brand name", ""),
                    "Scientific Name": cells.get("Scientific Name", ""),
                }
            )
        if list_name == "drugs-circulars":
            body = " ".join(value for label, value in detail if label == "Body")
            return self._by_recall(cells.get("Trade Name", ""), body)
        if list_name == "dhpc":
            return self._by_letter(cells.get("Product", ""))
        if list_name in ("drug-shortage", "drug-shortage-resolved"):
            brands: dict[str, list[ListedName]] = defaultdict(list)
            for label, value in detail:
                if label.lower() == "trade name" and value:
                    brands[normalize_text(core_name(value))].append(_listed_name(value))
            return self._by_generic_name(cells.get("Generic Name", ""), brands)
        if list_name == "safety-alert":
            return self._by_title(cells.get("Title", ""))
        if list_name == "drug-companies":
            return self._by_company_name(cells.get("Company Name", ""))
        return ()

    def _by_brand_and_substance(self, cells: Mapping[str, str]) -> tuple[RowLink, ...]:
        brand = normalize_text(core_name(cells.get("Trade Name", "")))
        wanted = _substances(cells.get("Scientific Name", ""))
        links = []
        for item in self._by_brand.get(brand, []) if brand else []:
            if item.has_substances(wanted):
                links.append(RowLink(item.register_number, "matched", "brand and substance agree"))
            else:
                links.append(
                    RowLink(item.register_number, "possible", "same brand, substance differs")
                )
        return tuple(links)

    def _by_generic_name(
        self, generic: str, brands: Mapping[str, Sequence[ListedName]] | None = None
    ) -> tuple[RowLink, ...]:
        brands = brands or {}
        wanted = _substances(generic)
        if not wanted:
            return ()
        seen: dict[str, LinkableProduct] = {}
        for word in {w.split()[0] for w in wanted}:
            for item in self._by_first_word.get(word, []):
                seen[item.register_number] = item
        links = []
        for item in seen.values():
            if not item.has_substances(wanted):
                continue
            listed = [
                name
                for brand, names in brands.items()
                if item.brand and _brand_related(brand, item.brand)
                for name in names
            ]
            if listed and item.generic_named:
                # Named after its substance: the row can mean any maker's product, unless no more
                # registered products of these substances fit its strength and form than it names.
                fitting = [
                    other
                    for other in seen.values()
                    if other.generic_named
                    and other.has_substances(wanted)
                    and "confirmed" in {_verdict(name, other) for name in listed}
                ]
                # SFDA writes a generic trade name once per product it means ("CYTARABINE
                # 100MG-1ML VIAL" three times for three makers): fitting products up to that count.
                naming = sum(_verdict(name, item) == "confirmed" for name in listed)
                if naming and len(fitting) <= naming:
                    links.append(RowLink(item.register_number, "matched", "generic and trade name"))
                else:
                    links.append(
                        RowLink(
                            item.register_number, "possible", "the row names only the substance"
                        )
                    )
            elif listed:
                verdicts = {_verdict(name, item) for name in listed}
                if "confirmed" in verdicts:
                    links.append(RowLink(item.register_number, "matched", "generic and trade name"))
                elif "unconfirmed" in verdicts:
                    # The row names the brand but no strength or form to compare. Only a brand
                    # with one registered product of these substances is certain to be it.
                    same = [
                        other
                        for other in self._by_brand.get(item.brand, [])
                        if other.has_substances(wanted)
                    ]
                    if len(same) == 1:
                        links.append(
                            RowLink(item.register_number, "matched", "generic and trade name")
                        )
                    else:
                        links.append(
                            RowLink(
                                item.register_number,
                                "possible",
                                "same trade name, strength or form not stated",
                            )
                        )
                else:
                    links.append(
                        RowLink(
                            item.register_number,
                            "possible",
                            "same trade name, a different strength or form",
                        )
                    )
            elif not brands:
                links.append(RowLink(item.register_number, "possible", "generic name only"))
            # else: the row names its trade names and this product is not one of them
        return tuple(links)

    def _by_title(self, title: str) -> tuple[RowLink, ...]:
        text = f" {normalize_text(title)} "
        found: dict[str, RowLink] = {}
        self._add_named_ingredients(found, text, "title")
        return tuple(found.values())

    def _add_named_ingredients(self, found: dict[str, RowLink], text: str, where: str) -> None:
        """Possible links to products one of whose ingredients the (padded, normalized) text names.
        Links already in `found` are kept."""
        words = set(text.split())
        for word in words & self._by_first_word.keys():
            for item in self._by_first_word[word]:
                for name in item.ingredients:
                    if _names_ingredient(name, text, words):
                        found.setdefault(
                            item.register_number,
                            RowLink(
                                item.register_number,
                                "possible",
                                f"{where} names {name.split()[0]}",
                            ),
                        )

    def _brands_named(self, text: str) -> list[LinkableProduct]:
        """Products whose brand the (padded, normalized) text names, as one to three words."""
        tokens = text.split()
        seen: dict[str, LinkableProduct] = {}
        for size in (1, 2, 3):
            for start in range(len(tokens) - size + 1):
                phrase = " ".join(tokens[start : start + size])
                for item in self._by_brand.get(phrase, []):
                    seen[item.register_number] = item
        return list(seen.values())

    def _by_recall(self, trade_name: str, body: str) -> tuple[RowLink, ...]:
        found: dict[str, RowLink] = {}
        # a register number written in the circular is strong evidence; batch numbers are shorter
        for token in set(_REGISTER_TOKEN.findall(body)):
            for item in self._by_register.get(token, []):
                found[item.register_number] = RowLink(
                    item.register_number, "matched", "register number named in the circular"
                )
        brand = normalize_text(core_name(trade_name))
        text = f" {normalize_text(body)} "
        words = set(text.split())
        for item in self._by_brand.get(brand, []) if brand else []:
            if item.register_number in found:
                continue
            if item.ingredients and all(
                _names_ingredient(n, text, words) for n in item.ingredients
            ):
                found[item.register_number] = RowLink(
                    item.register_number, "matched", "brand and substances named in the circular"
                )
            else:
                found[item.register_number] = RowLink(
                    item.register_number, "possible", "same brand, substance not confirmed"
                )
        return tuple(found.values())

    def _by_letter(self, product_text: str) -> tuple[RowLink, ...]:
        text = f" {normalize_text(product_text)} "
        words = set(text.split())
        found: dict[str, RowLink] = {}
        for item in self._brands_named(text):
            if item.ingredients and all(
                _names_ingredient(n, text, words) for n in item.ingredients
            ):
                found[item.register_number] = RowLink(
                    item.register_number, "matched", "brand and substances named in the letter"
                )
            else:
                found[item.register_number] = RowLink(
                    item.register_number, "possible", "brand named, substances not confirmed"
                )
        self._add_named_ingredients(found, text, "letter")
        return tuple(found.values())

    def _by_company_name(self, company: str) -> tuple[RowLink, ...]:
        found: dict[str, RowLink] = {
            item.register_number: RowLink(item.register_number, "matched", "company name agrees")
            for item in self._by_company.get(_company_key(company), [])
        }
        core = _company_core(company)
        for item in self._by_company_core.get(core, []) if core else []:
            found.setdefault(
                item.register_number,
                RowLink(
                    item.register_number,
                    "possible",
                    "same company name once legal form and site are dropped",
                ),
            )
        return tuple(found.values())
