"""Arabic spellings of common generic names, mapped to the English name the registry uses.

The registry writes ingredients in English only. An Arabic generic name is found today only when
some product's Arabic trade name happens to contain it ("وارفارين ماكليودز"); "انسولين" or
"ليفوثيروكسين" are in no Arabic trade name, so they found unrelated products. This table is the
alias table the project rules ask for: spellings of names, not medical facts. Keys are written as
people type them; they are normalized (hamza, alef, ta marbuta, diacritics) when the module loads.
"""

from pharmavique.shared_kernel.text import normalize_text

_SPELLINGS: dict[str, tuple[str, ...]] = {
    "insulin": ("انسولين", "إنسولين", "انسيولين"),
    "cetirizine": ("سيتريزين", "ستريزين", "سيتيريزين"),
    "levocetirizine": ("ليفوسيتريزين",),
    "loratadine": ("لوراتادين",),
    "desloratadine": ("ديسلوراتادين",),
    "fexofenadine": ("فيكسوفينادين", "فكسوفينادين"),
    "losartan": ("لوسارتان",),
    "valsartan": ("فالسارتان",),
    "irbesartan": ("ايربيسارتان", "اربيسارتان"),
    "candesartan": ("كانديسارتان",),
    "telmisartan": ("تلميسارتان",),
    "salbutamol": ("سالبيوتامول", "سالبوتامول", "سالبيتامول"),
    "hydrocortisone": ("هيدروكورتيزون", "هيدروكورتيزن"),
    "betamethasone": ("بيتاميثازون",),
    "dexamethasone": ("ديكساميثازون", "دكساميثازون"),
    "prednisolone": ("بريدنيزولون",),
    "levothyroxine": ("ليفوثيروكسين", "ثيروكسين", "ليفوثيروكسن"),
    "esomeprazole": ("اسومبرازول", "إيسوميبرازول", "ايسوميبرازول", "اسوميبرازول"),
    "omeprazole": ("اوميبرازول", "أوميبرازول"),
    "pantoprazole": ("بانتوبرازول",),
    "lansoprazole": ("لانسوبرازول",),
    "aciclovir": ("اسيكلوفير", "أسيكلوفير", "اسيكلوفيير"),
    "acyclovir": ("اسيكلوفير", "أسيكلوفير"),
    "valaciclovir": ("فالاسيكلوفير",),
    "vitamin d": ("فيتامين د", "فيتامين دال"),
    "cholecalciferol": ("كوليكالسيفيرول",),
    "iron": ("حديد",),
    "ferrous": ("حديد",),
    "zinc": ("زنك",),
    "folic acid": ("فوليك", "حمض الفوليك", "فوليك اسيد"),
    "semaglutide": ("سيماجلوتايد", "سيماجلوتيد", "سماجلوتايد"),
    "liraglutide": ("ليراجلوتايد", "ليراجلوتيد"),
    "dulaglutide": ("دولاجلوتايد",),
    "metformin": ("ميتفورمين", "متفورمين"),
    "sitagliptin": ("سيتاجليبتين",),
    "empagliflozin": ("امباجليفلوزين", "إمباجليفلوزين"),
    "dapagliflozin": ("داباجليفلوزين",),
    "gliclazide": ("جليكلازيد",),
    "glimepiride": ("جليميبرايد", "جليمبيرايد"),
    "atorvastatin": ("اتورفاستاتين", "أتورفاستاتين"),
    "rosuvastatin": ("روزوفاستاتين",),
    "simvastatin": ("سيمفاستاتين",),
    "amlodipine": ("املوديبين", "أملوديبين"),
    "bisoprolol": ("بيسوبرولول",),
    "atenolol": ("اتينولول", "أتينولول"),
    "carvedilol": ("كارفيديلول",),
    "furosemide": ("فوروسيميد",),
    "hydrochlorothiazide": ("هيدروكلوروثيازيد",),
    "warfarin": ("وارفارين",),
    "apixaban": ("ابيكسابان", "أبيكسابان"),
    "rivaroxaban": ("ريفاروكسابان",),
    "clopidogrel": ("كلوبيدوجريل", "كلوبيدوقريل"),
    "acetylsalicylic acid": ("اسبرين", "أسبرين", "اسبيرين"),
    "paracetamol": ("باراسيتامول", "براسيتامول", "باراسيتمول"),
    "ibuprofen": ("ايبوبروفين", "إيبوبروفين", "ابوبروفين"),
    "diclofenac": ("ديكلوفيناك",),
    "naproxen": ("نابروكسين",),
    "celecoxib": ("سيليكوكسيب",),
    "tramadol": ("ترامادول",),
    "amoxicillin": ("اموكسيسيلين", "أموكسيسيلين", "اموكسسيلين"),
    "azithromycin": ("ازيثرومايسين", "أزيثرومايسين", "ازيثرومايسن"),
    "clarithromycin": ("كلاريثرومايسين",),
    "ciprofloxacin": ("سيبروفلوكساسين",),
    "levofloxacin": ("ليفوفلوكساسين",),
    "cefuroxime": ("سيفوروكسيم",),
    "ceftriaxone": ("سيفترياكسون",),
    "cefixime": ("سيفيكسيم",),
    "metronidazole": ("ميترونيدازول",),
    "fluconazole": ("فلوكونازول",),
    "montelukast": ("مونتيلوكاست",),
    "budesonide": ("بوديسونايد", "بوديزونيد"),
    "fluticasone": ("فلوتيكازون",),
    "gabapentin": ("جابابنتين",),
    "pregabalin": ("بريجابالين",),
    "sertraline": ("سيرترالين",),
    "escitalopram": ("اسيتالوبرام", "إسيتالوبرام"),
    "fluoxetine": ("فلوكستين", "فلوكسيتين"),
    "domperidone": ("دومبيريدون",),
    "ondansetron": ("اوندانسيترون", "أوندانسيترون"),
    "loperamide": ("لوبيراميد",),
    "sildenafil": ("سيلدينافيل",),
    "tadalafil": ("تادالافيل",),
    "tamsulosin": ("تامسولوسين",),
    "finasteride": ("فيناسترايد",),
    "enoxaparin": ("اينوكسابارين", "إينوكسابارين"),
    "heparin": ("هيبارين",),
    "allopurinol": ("الوبيورينول", "ألوبيورينول"),
    "colchicine": ("كولشيسين", "كولتشيسين"),
    "methotrexate": ("ميثوتريكسات",),
    "isotretinoin": ("ايزوتريتينوين", "إيزوتريتينوين"),
}

ARABIC_TO_ENGLISH: dict[str, tuple[str, ...]] = {}
for _english, _spellings in _SPELLINGS.items():
    for _spelling in _spellings:
        _key = normalize_text(_spelling)
        ARABIC_TO_ENGLISH[_key] = (*ARABIC_TO_ENGLISH.get(_key, ()), _english)


def english_names(normalized_query: str) -> tuple[str, ...]:
    """The English generic names an Arabic query spells, or () when it spells none.

    The whole query is looked up, then the query without a leading "ال". Only an exact spelling
    counts: a near spelling of a generic name is left to the fuzzy search, which already handles
    names whose Arabic form is in some trade name.
    """
    for text in (normalized_query, normalized_query.removeprefix("ال")):
        found = ARABIC_TO_ENGLISH.get(text)
        if found:
            return found
    return ()
