"""List the conditions each product's ingredients are contraindicated with, from a source."""

import re
from collections.abc import Sequence

from pharmavique.interactions.application.ports import ContraindicationStore
from pharmavique.interactions.contracts.queries import (
    Contraindication,
    ContraindicationReport,
    ProductIngredients,
)
from pharmavique.interactions.domain.names import candidate_keys

__all__ = ["ListContraindications"]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def names_the_condition(disease: str, text: str) -> bool:
    """True only when the label text itself contains the condition's name.

    MeDIC maps label sentences to ontology names by software; a row whose own text does not say
    the condition is not shown, because we cannot tell a correct mapping from a wrong one.
    """
    return _squash(disease) in _squash(text)


# Words that make a sentence say the drug must not be used.
_CUE = re.compile(
    r"contraindicated|should not|must not|not be (?:used|given|administered|taken)"
    r"|do not (?:use|give|administer|take)|not receive",
    re.IGNORECASE,
)
# A sentence that limits what it says to one group of patients, one use or one combination: what
# a US label says about premature babies, pregnant women or a drug taken with colchicine is not
# about every product with the ingredient.
_NARROW = re.compile(
    r"preterm|premature infant|neonat|pregnant women with|first trimester|concomitant"
    r"|co-?administ|in combination with|taken with|application|on the skin|of skin|damaged skin"
    r"|\bindicated\b|adjunct"  # a sentence about what the drug treats is not a contraindication
    r"|for treating|pregnan"  # a use, or pregnancy only (a pregnancy row is kept, see below)
    # a hedge: "probably should not", "should not ordinarily", "may be contraindicated"
    r"|probably|ordinarily|may be contraindicated|result from conditions|may also result"
    r"|after taking"  # "asthma ... after taking aspirin": a reaction, not asthma itself
    r"|strength is contraindicated"  # "the 10% strength is contraindicated": one strength
    r"|undesirable",  # "when miosis is undesirable, e.g. in ... glaucoma": a situation
    re.IGNORECASE,
)
# A route (an eye drop, an implant, an inhaler, a rectal or vaginal form) named in the opening of
# the label, where it says what product it is about, or in the sentence itself: what it says is not
# shown, because a Saudi product with the ingredient may be a tablet. Further down a label only
# lists situations ("spinal puncture" in a warfarin label), which say nothing about its route.
_LABEL_OPENING = 150
_ROUTE = re.compile(
    r"ocular|ophthalmic|cornea|conjunctiv|of the eye|intraocular|intravitreal|intrarectal"
    r"|rectal|vaginal|intrauterine|inhal|nasal|topical|epidural|intrathecal|spinal"
    r"|intra-articular|hysterosalpingograph|irrigation"
    r"|\b(?:cream|ointment|gel|lotion|shampoo|foam|eye drops?|ear drops?|suppositor[a-z]*"
    r"|pessar[a-z]*|implant|patch|transdermal|hfa|diskus|flexhaler|respimat|suspension)\b",
    re.IGNORECASE,
)
# A short line with no verb is an item of the contraindications list ("Hemorrhagic tendencies or
# blood dyscrasias."); a line with a verb is a statement that has to say "contraindicated" itself
# ("Atherosclerosis is a chronic process." is not a contraindication).
_LIST_ITEM_WORDS = 12
_VERB = re.compile(
    r"\b(?:is|are|was|were|be|been|may|might|can|could|should|would|will|has|have|had|include"
    r"|includes|including|reported|occur|occurs|appear|appears)\b",
    re.IGNORECASE,
)
# A label text that also says what the drug treats: its bare list items may be indications
# ("cryptitis;"), so only statements that say "contraindicated" count there.
_TREATS = re.compile(
    r"\bindicated for|adjunct|treatment of|relief of|for the relief", re.IGNORECASE
)
_SENTENCE = re.compile(
    r"(?<=[.;\u2022])\s+|\s+(?=\(\s*\d+(?:\.\d+)?\s*\))"
    r"|\s+[\u2013\u2212\u2022]\s+|\n+"  # list items after a dash, a bullet or a new line
)


def _qualified(wanted: str, sentence: str, ingredient: str) -> bool:
    """The condition is named only as a qualifier of something else: "with or without coma",
    "shock (nonanaphylactic)", "diarrhea caused by poisoning", "patients with psoriasis ... who
    have", or a heading ("Myocardial Infarction Metoprolol is contraindicated ...")."""
    at = sentence.find(wanted)
    before, after = sentence[:at], sentence[at + len(wanted) :]
    if before.rstrip().endswith("with or without"):
        return True
    if re.match(r"\s*\(non", after):
        return True
    if re.match(r"s?\s*(?:caused by|secondary to|due to|associated with)\b", after):
        return True
    if re.match(r"\s*(?:or [a-z ]{3,40}?)?\s*(?:who|with)\b", after) and "patients with" in before:
        return True
    head = ingredient.split()[0] if ingredient.split() else ""
    return bool(
        head
        and not before.strip()
        and after.strip().startswith(head)
        and sentence.count(wanted) == 1
    )


def _is_list_item(sentence: str) -> bool:
    return len(sentence.split()) <= _LIST_ITEM_WORDS and not _VERB.search(sentence)


def says_it_is_contraindicated(disease: str, text: str, ingredient: str = "") -> bool:
    """The label says the drug is contraindicated with this condition, for every form of it.

    The condition must be named in a sentence that says "contraindicated" (or "should not ...").
    A label that never uses such words is a bare list of conditions (the contraindications
    section itself) and counts as saying it. A sentence limited to one route, form or group of
    patients, or a label written for one route, is not shown: we cannot tell whether a Saudi
    product has that route.
    """
    if _ROUTE.search(text[:_LABEL_OPENING]):
        return False
    wanted = _squash(disease)
    sentences = [_squash(s) for s in _SENTENCE.split(text) if s.strip()]
    naming = [s for s in sentences if wanted in s]
    if not naming:
        return False
    lists = not _TREATS.search(text)
    if _CUE.search(text):
        naming = [s for s in naming if _CUE.search(s) or (lists and _is_list_item(s))]
    elif not lists:
        return False
    pregnancy_row = "pregnan" in wanted
    return any(
        not (_NARROW.search(s.replace("pregnan", "")) if pregnancy_row else _NARROW.search(s))
        and not _ROUTE.search(s)
        and not _qualified(wanted, s, ingredient.lower())
        for s in naming
    )


# A product used on the skin, the eye, the nose, the ear, the mouth or by inhalation: US labels of
# tablets and injections say nothing about it (lidocaine gel is not contraindicated in heart
# block), and a label of its own form cannot be told apart, so none is shown for it.
_LOCAL_USE = re.compile(
    r"topical|cutaneous|dermal|ophthalm|ocular|conjunctival|intravitreal|\beye|nasal|\bnose"
    r"|otic|auricular|\bear\b|rectal|vaginal|dental|oromucosal|gingival|buccal|oropharyn"
    r"|epilesional|inhal|nebuli|scalp|intrauterine|irrigation|\bcream|ointment|\bgel\b|lotion"
    r"|shampoo|mouthwash|suppositor|pessar|eye drops|ear drops|nasal spray",
    re.IGNORECASE,
)


def local_use(route: str | None, dosage_form: str | None) -> bool:
    return bool(_LOCAL_USE.search(f"{route or ''} {dosage_form or ''}"))


def _more_specific_named(disease: str, others: set[str], text: str) -> bool:
    """A longer condition recorded for the same ingredient contains this one and this label
    names it too ("asthma" inside "status asthmaticus"): the general name on its own would claim
    more than the label does."""
    said = _squash(text)
    return any(other != disease and disease in other and other in said for other in others)


class ListContraindications:
    def __init__(self, store: ContraindicationStore) -> None:
        self._store = store

    async def run(self, products: Sequence[ProductIngredients]) -> ContraindicationReport:
        entries = [
            (p.register_number, name, set(candidate_keys(name)))
            for p in products
            for name in p.ingredients
        ]
        local = {p.register_number for p in products if local_use(p.route, p.dosage_form)}
        every_key = {key for _, _, keys in entries for key in keys}
        records = await self._store.for_ingredients(every_key)
        items: dict[tuple[str, str, str], Contraindication] = {}
        hidden: set[tuple[str, str, str]] = set()
        conditions: dict[str, set[str]] = {}
        for record in records:
            conditions.setdefault(record.ingredient, set()).add(record.disease)
        for register, name, keys in entries:
            for record in records:
                if record.ingredient in keys:
                    if register in local or not (
                        names_the_condition(record.disease, record.text)
                        and says_it_is_contraindicated(
                            record.disease, record.text, record.ingredient
                        )
                        and not _more_specific_named(
                            record.disease,
                            conditions[record.ingredient],
                            record.text,
                        )
                    ):
                        hidden.add((register, record.ingredient, record.disease))
                        continue
                    # one row per substance, even when the registry names it twice
                    # ("ACETYLSALICYLIC ACID" and "ASPIRIN" are one key)
                    items.setdefault(
                        (register, record.ingredient, record.disease),
                        Contraindication(
                            register, name, record.disease, record.text, record.source
                        ),
                    )
        ordered = sorted(items.values(), key=lambda i: (i.register_number, i.disease, i.ingredient))
        return ContraindicationReport(
            items=tuple(ordered), complete=False, hidden_unverified=len(hidden - set(items))
        )
