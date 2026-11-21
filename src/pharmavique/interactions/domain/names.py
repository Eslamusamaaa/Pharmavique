"""Match our registry's ingredient names to the names interaction sources use.

SFDA writes `AMLODIPINE BESILATE`, `LOSARTAN POTASSIUM` and `PARACETAMOL`. Interaction sources
(mostly US) say `amlodipine`, `losartan` and `acetaminophen`. A name is tried as written first, then
without its salt or ester word, then under the spelling the sources use. The registry's name is
never changed: this only produces the keys to look up.
"""

import re

# Words that name the salt, ester or hydration of a drug, not the drug itself.
_SALT_WORDS = frozenset(
    {
        "hydrochloride", "dihydrochloride", "hcl", "besilate", "besylate", "sodium", "disodium",
        "potassium", "calcium", "magnesium", "sulfate", "sulphate", "maleate", "tartrate",
        "fumarate", "succinate", "mesylate", "mesilate", "acetate", "diacetate", "phosphate",
        "citrate", "bromide", "hydrobromide", "nitrate", "hydrate", "monohydrate", "dihydrate",
        "hemihydrate", "trihydrate", "pentahydrate", "anhydrous", "hydrated", "valerate",
        "propionate", "dipropionate", "tosylate", "lactate", "gluconate", "oxalate", "medoxomil",
        "cilexetil", "axetil", "furoate", "etexilate", "proxetil", "pivoxil", "hexetil",
    }
)  # fmt: skip
# What is left after stripping must be a drug name, not a bare anion ("sodium chloride").
_BARE_ANIONS = frozenset(
    {
        "chloride", "bromide", "iodide", "nitrate", "phosphate", "sulfate", "sulphate",
        "acetate", "citrate", "lactate", "gluconate", "carbonate", "oxide", "hydroxide",
        "bicarbonate",
    }
)  # fmt: skip
# International names the registry uses, to the names the interaction sources use.
_ALIASES = {
    "paracetamol": "acetaminophen",
    "cefalexin": "cephalexin",
    "colecalciferol": "cholecalciferol",
    "adrenaline": "epinephrine",
    "noradrenaline": "norepinephrine",
    "frusemide": "furosemide",
    "lignocaine": "lidocaine",
    "glibenclamide": "glyburide",
    "ciclosporin": "cyclosporine",
    "thyroxine": "levothyroxine",
    "pethidine": "meperidine",
    "vitamin c": "ascorbic acid",
    "retinol": "vitamin a",
    "tocopherol": "vitamin e",
    "amoxycillin": "amoxicillin",
    "hyoscine": "scopolamine",
    "levomepromazine": "methotrimeprazine",
    "chlorphenamine": "chlorpheniramine",
    "pancreatin": "pancrelipase",
    "aciclovir": "acyclovir",
    "indometacin": "indomethacin",
    "ethinyl estradiol": "ethinylestradiol",
    "sulphasalazine": "sulfasalazine",
}  # fmt: skip


def normalize(name: str) -> str:
    """Lower case, letters and spaces only: DL-ALPHA TOCOFERIL ACETATE becomes
    `dl alpha tocoferil acetate`."""
    return " ".join(re.sub(r"[^a-z]+", " ", name.lower()).split())


def _stripped(key: str) -> str:
    words = [w for w in key.split() if w not in _SALT_WORDS]
    if not words or (len(words) == 1 and words[0] in _BARE_ANIONS):
        return key
    return " ".join(words)


def _plain(name: str) -> str:
    """The name without what is in brackets: `PYRIDOXINE (VITAMIN B6)` gives `pyridoxine`."""
    return normalize(re.sub(r"\([^)]*\)", " ", name))


def base_key(name: str) -> str:
    """The key that stands for the drug itself: salt words dropped, source spelling applied."""
    key = _stripped(_plain(name))
    return _ALIASES.get(key, key)


def candidate_keys(name: str) -> tuple[str, ...]:
    """Every key to look up, most exact first, without repeats."""
    full = normalize(name)
    if not full:
        return ()
    plain = _plain(name)
    keys = [full, _ALIASES.get(full, full), plain, _ALIASES.get(plain, plain)]
    stripped = _stripped(plain)
    keys.extend([stripped, _ALIASES.get(stripped, stripped)])
    return tuple(dict.fromkeys(key for key in keys if key))
