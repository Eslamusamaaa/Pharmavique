"""Triage of a question before the model sees it (audit 2026-11, Part C; ADR-024).

The model does not decide what kind of question it got. These rules do, so the decision is the same
every time, can be tested, and is recorded with the answer:

- `RED_FLAG`: the person reports a sign that needs urgent care (a sudden worst headache, weakness
  or numbness, trouble speaking, vision loss, fever with a stiff neck, a head injury, chest pain).
  The reply is fixed and no medicine is discussed. Reading *about* a red flag ("what is a
  thunderclap headache?") is not one: a red flag counts only when someone reports it.
- `INTERACTION`, `DRUG_SAFETY` (does a medicine suit a condition: pregnancy, heart disease...),
  `SYMPTOM_TREATMENT` (what to take for a symptom), `DRUG_INFO` (what a medicine is, is for, its
  side effects), `OTHER`. Each gives the model a short instruction for that kind of question.
- The dialect of the answer follows the question (owner, 2026-11-26): Egyptian for Egyptian,
  English for English, light Saudi otherwise.

The rules run on `normalize_text` output: no diacritics, bare alef, ha for ta marbuta, ya for alef
maqsura, no punctuation. Pure functions, no framework.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from pharmavique.shared_kernel.text import normalize_text


class Intent(StrEnum):
    RED_FLAG = "red_flag"
    INTERACTION = "interaction"
    DRUG_SAFETY = "drug_safety"
    SYMPTOM_TREATMENT = "symptom_treatment"
    DRUG_INFO = "drug_info"
    OTHER = "other"


class Dialect(StrEnum):
    EGYPTIAN = "egyptian"
    SAUDI = "saudi"
    ENGLISH = "english"


@dataclass(frozen=True, slots=True)
class Triage:
    intent: Intent
    dialect: Dialect
    symptoms: tuple[str, ...] = ()
    red_flags: tuple[str, ...] = ()

    @property
    def guidance(self) -> str:
        """The instruction for the model for this kind of question, plus the dialect."""
        parts = [_GUIDANCE.get(self.intent, "")]
        if self.intent is Intent.SYMPTOM_TREATMENT and "headache" in self.symptoms:
            parts.append(_HEADACHE_GUIDANCE)
        parts.append(_DIALECT_GUIDANCE[self.dialect])
        return " ".join(part for part in parts if part)


def _rx(*rules: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{rule})" for rule in rules))


# ---- who is reporting: a red flag counts only when someone has it -----------------------------
_REPORTING = _rx(
    r"\b(عندي|عنده|عندها|عندو|جالي|جاله|جالها|جاني|جاتني|بيجيلي|يجيني|حاسس|حاسه|احس|اعاني|يعاني|"
    r"تعاني|معايا|معاي|معاه|معاها|ايدي|رجلي|راسي|رقبتي|صدري|وشي|خبطت|وقعت|ابني|بنتي|امي|ابوي|"
    r"ابويا|زوجي|زوجتي|جوزي|مراتي|اخويا|اختي|ايوه|ايوا)\b",
    r"\b(i|i ve|ive|im|my|me|we|our|he|she|his|her)\b",
)

# ---- red flags --------------------------------------------------------------------------------
_HEAD = r"(صداع|راس|راسي|الراس|دماغ|دماغي|headache)"
_RED_FLAGS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "sudden_severe_headache",
        _rx(
            r"(اسوا|اشد|اقوي|اقوى) صداع",
            rf"{_HEAD}.{{0,30}}(فجاه|مفاجي|مفاجئ|زي الرعد|كالرعد)",
            rf"(فجاه|مفاجي|مفاجئ).{{0,30}}{_HEAD}",
            r"worst headache",
            r"sudden(ly)? .{0,20}headache|headache .{0,30}sudden",
            r"thunderclap",
        ),
    ),
    (
        "weakness_or_numbness",
        _rx(
            r"(ضعف|تنميل|خدر|شلل|تقل|تنمل).{0,20}\b(ايدي|ايده|ايدها|ايد|يدي|يد|رجلي|رجله|رجل|"
            r"وشي|وشه|الوش|الوجه|وجهي|نص|جنب|ناحيه|الجسم|جسمي|دراعي|ذراعي|دراع|ذراع)\b",
            r"\b(weakness|numbness|tingling)\b.{0,20}\b(in|on|of)\b",
            r"\b(face|mouth) (drooping|droop)\b",
        ),
    ),
    (
        "speech_difficulty",
        _rx(
            r"(صعوبه|تقل|لخبطه|تلعثم).{0,10}(الكلام|كلامي|النطق)",
            r"مش (قادر|قادره|عارف|عارفه) (يتكلم|اتكلم|تتكلم|انطق|ينطق)",
            r"ما (اقدر|يقدر|تقدر) (اتكلم|يتكلم|تتكلم)",
            r"لساني (تقيل|ثقيل)",
            r"slurred speech|trouble (speaking|talking)|can ?t speak",
        ),
    ),
    (
        "vision_change",
        _rx(
            r"زغلله|زغلل",
            r"(فقدت|راح|اختفي|اختفى|ضاع) (النظر|نظري|الشوف)",
            r"(مش|ما) (شايف|شايفه|اشوف)",
            r"(رويه|رؤيه) مزدوجه|شايف (اتنين|اثنين)",
            r"(vision loss|lost (my )?vision|double vision|blurred vision|can ?t see)",
        ),
    ),
    (
        "fever_and_stiff_neck",
        _rx(
            r"(تيبس|تصلب|تشنج|شد).{0,15}(الرقبه|رقبتي|رقبته|رقبتها)",
            r"(الرقبه|رقبتي|رقبته|رقبتها) (متيبسه|ناشفه|مشدوده|متصلبه|واقفه)",
            r"stiff neck|neck (is )?stiff",
        ),
    ),
    (
        "head_injury",
        _rx(
            r"(خبطه|ضربه|خبطت|ضربت|وقعت).{0,25}(راس|راسي|راسه|دماغ|دماغي)",
            r"head injury|hit (my|his|her) head|bumped (my|his|her) head",
        ),
    ),
    (
        "chest_pain",
        _rx(
            r"(الم|وجع|ضغط|تقل).{0,10}(في )?(الصدر|صدري|صدره|صدرها)",
            r"chest (pain|tightness)|pain in (my|the) chest",
        ),
    ),
)

# ---- kinds of question --------------------------------------------------------------------------
_INTERACTION = _rx(
    r"تداخل|تتداخل|يتداخل|تعارض|تتعارض|يتعارض|تفاعل",
    r"\b(اخد|اخذ|ناخد|ياخد|تاخد|تاخذ|ياخذ|اشرب|استعمل|استخدم)\b.{1,40}\b(مع)\b",
    r"مع بعض|مع بعضهم|سوا|سوى",
    r"\binteract(ion|ions|s)?\b",
    r"\btake\b.{1,40}\bwith\b|\btogether\b|\bcombine\b|\bcombining\b",
)
_CONDITION = (
    r"(حامل|الحمل|حمل|رضاعه|مرضع|بارضع|القلب|قلب|الضغط|ضغط|الكلي|كلي|الكبد|كبد|السكر|سكر|"
    r"الربو|ربو|قرحه|طفل|اطفال|الاطفال|رضيع|كبار السن)"
)
_DRUG_SAFETY = _rx(
    rf"\b(امن|امان|ينفع|يصلح|مسموح|خطر|خطير|مضر)\b.{{0,40}}{_CONDITION}",
    rf"{_CONDITION}.{{0,40}}\b(امن|ينفع|يصلح|مسموح|ياخد|تاخد|ياخذ|تاخذ|خطر|مضر)\b",
    r"\b(safe|safety|ok|okay|allowed)\b.{0,40}\b(pregnan\w*|breastfeed\w*|heart|blood pressure|"
    r"kidney|liver|diabet\w*|asthma|ulcer|child\w*|kids?|bab\w*|elderly)\b",
    r"\b(pregnan\w*|breastfeed\w*|heart disease)\b.{0,40}\b(safe|take|use)\b",
    r"\b(risks?|dangers?) of\b|\bis it (safe|dangerous)\b",
    r"(مخاطر|اضرار|خطوره)\b",
)
_SYMPTOMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("headache", _rx(r"صداع|شقيقه|وجع (في )?(الراس|راسي|دماغي)|headache|migraine")),
    ("stomach", _rx(r"مغص|معدتي|بطني|حموضه|stomach|abdominal|heartburn")),
    ("allergy", _rx(r"حساسيه|allerg\w*")),
    ("cough_cold", _rx(r"كحه|سعال|زكام|برد|رشح|cough|cold|flu")),
    ("fever", _rx(r"حراره|سخونيه|سخونه|حمي|fever")),
    ("pain", _rx(r"\b(الم|وجع|بيوجعني|يوجعني)\b|\bpain\b|\bache\b")),
    ("bowel", _rx(r"اسهال|امساك|diarrh\w*|constipat\w*")),
    ("nausea", _rx(r"غثيان|ترجيع|استفراغ|nausea|vomit\w*")),
    ("sleep", _rx(r"ارق|مش عارف انام|ما اقدر انام|insomnia|can ?t sleep")),
)
_TREATMENT_REQUEST = _rx(
    r"\b(اخد|اخذ|ناخد|ناخذ|اكل|استعمل|استخدم|اشرب)\s+(ايه|ايش|وش|اي)\b",
    r"\b(ايه|ايش|وش)\s+(اخد|اخذ|ناخد|ناخذ|استعمل|استخدم|اشرب)\b",
    r"\b(ايه|ايش|وش|اي)\s+(الدوا|الدواء|العلاج|المسكن|دوا|دواء|علاج|مسكن)\b",
    r"\b(ايه|ايش|وش)\s+(اللي|الي)\s+(ينفع|يفيد|يساعد|يريح|يخفف)\b",
    r"\b(رشحلي|رشح لي|ترشحلي|ترشح لي|رشح|ترشح|انصحني|تنصحني|اقترح|اقترحلي)\b",
    r"\b(عايز|عاوز|ابغي|ابي|محتاج|احتاج)\s+(دوا|دواء|علاج|مسكن|حاجه|شي)\b",
    r"\b(دوا|دواء|علاج|مسكن)\s+(ل|لل|للـ)",
    r"\bwhat\b.{0,30}\b(medicine|medication|drug|pill|active ingredient)s?\b",
    r"\bwhat (can|should|could) i (take|use)\b|\bwhat (can|could|would) help\b|\bwhat helps\b",
    r"\brecommend\b|\bsuggest\b.{0,20}\b(medicine|drug)",
)
_DRUG_INFO = _rx(
    r"استخدام|استخدامات|بيستخدم|يستخدم|تستخدم|بيعالج|يعالج|فايده|فوايد|الماده الفعاله|"
    r"اعراض جانبيه|الاعراض الجانبيه|اثار جانبيه|الاثار الجانبيه|الفرق بين|بيشتغل|يشتغل|"
    r"ميكانيكيه|ما هو|ما هي|ايه هو|ايه هي|ايش هو|وش هو|يعني ايه|ايه رايك|رايك",
    r"\bused for\b|\buse(s)? of\b|\bactive ingredient\b|\bside effects?\b|\bdifference between\b|"
    r"\bwhat is\b|\bwhat are\b|\bhow does\b.{0,30}\bwork\b|\bmechanism\b|\bwhat do you think\b|"
    r"\bindications?\b|\btell me (about|what)\b",
)

# ---- dialect ------------------------------------------------------------------------------------
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")
_EGYPTIAN = _rx(
    r"\b(ايه|عايز|عاوز|عايزه|ازاي|دلوقتي|كده|كدا|بتاع|بتاعي|بتاعتي|مفيش|مافيش|اوي|النهارده|"
    r"بقالي|ليه|فين|اخد|خد|هاخد|باخد|مباخدش|ده|دي|دول|كويس|جامد|بيجيلي|جالي|ايوه|بس|"
    r"خالص|عشان|علشان|حاجه|مش)\b",
)
_SAUDI = _rx(
    r"\b(وش|ايش|ابغي|ابغا|ابي|الحين|زين|كذا|يبغي|تبغي|مره|وايد|ليش|وين|اخذ|ابخذ|شي|ترا|"
    r"يعطيك|عساك)\b",
)

# ---- guidance for the model (English: the system prompt is English) ---------------------------
_GUIDANCE = {
    Intent.DRUG_INFO: (
        "Question type: general information about a medicine. Answer it directly from your tools "
        "(what it is, its active ingredient, what the sources say it is used for, how it works, "
        "warnings), with citations. Do not ask about the person's symptoms, history or other "
        "medicines: they asked for information, not treatment."
    ),
    Intent.SYMPTOM_TREATMENT: (
        "Question type: the person describes a symptom and asks what to take. Do not treat a named "
        "condition as a confirmed diagnosis. In one answer: (1) the general medicine categories "
        "used for this symptom, from search_documents or the web search, cited, and that the right "
        "one depends on how severe it is and on the person; (2) you may name registered products "
        "with those ingredients (search_drugs), saying for each prescription-only product that it "
        "needs a doctor's prescription; (3) a short list of what you still need to know: how "
        "severe and how long, other symptoms, age, pregnancy or breastfeeding, chronic illnesses "
        "(heart, blood pressure, kidney, liver, stomach ulcer), other medicines, allergies. Never "
        "a dose, never 'this is your treatment'. If the person already answered these in the "
        "conversation, use the answers and do not ask again."
    ),
    Intent.INTERACTION: (
        "Question type: whether medicines can be combined. Look every medicine up with "
        "search_drugs, then call check_interactions with their register numbers. Say which of "
        "three it is: an interaction is documented (its severity as the source rates it, what it "
        "means, the source); no interaction is recorded in the sources checked (say that this is "
        "not proof that the combination is safe); or the sources do not cover an ingredient. "
        "Never call a combination safe. Ask about other medicines or conditions only when they "
        "change the answer."
    ),
    Intent.DRUG_SAFETY: (
        "Question type: whether a medicine suits a condition or a group (pregnancy, heart disease, "
        "children...). Look the exact medicine up, then call contraindications and search the "
        "documents for its warnings. Say what the sources record and name them; when they record "
        "nothing, say so, and that this is not a clearance. Never reassure; say that the person's "
        "doctor must assess it."
    ),
}
_HEADACHE_GUIDANCE = (
    "For a headache or migraine, look up and cite: simple painkillers (paracetamol, NSAIDs such as "
    "ibuprofen) and the triptans (migraine-specific, prescription-only, not suitable for everyone, "
    "for example people with heart disease, uncontrolled blood pressure or a past stroke). Do not "
    "assume it is a migraine unless the person said so."
)
_DIALECT_GUIDANCE = {
    Dialect.EGYPTIAN: (
        "Write the answer in everyday Egyptian Arabic, as the person writes; keep the English "
        "names of medicines and medical terms where they help, and explain each term."
    ),
    Dialect.SAUDI: "Write the answer in everyday light Saudi Arabic and explain each medical term.",
    Dialect.ENGLISH: "Write the answer in plain English and explain each medical term.",
}


def classify(question: str, earlier_questions: Sequence[str] = ()) -> Triage:
    """The triage of `question`; `earlier_questions` are the person's earlier turns, oldest first,
    so an answer to a follow-up question keeps the kind of the question it answers."""
    text = normalize_text(question)
    dialect = _dialect(question, text)
    symptoms = _symptoms(text)
    reporting = _REPORTING.search(text) is not None
    flags = tuple(name for name, rule in _RED_FLAGS if rule.search(text)) if reporting else ()
    if flags:
        return Triage(Intent.RED_FLAG, dialect, symptoms, flags)
    intent = _intent(text, symptoms)
    if intent is Intent.OTHER and earlier_questions:
        earlier = classify(earlier_questions[-1])
        if earlier.intent is not Intent.RED_FLAG:
            return Triage(
                earlier.intent, dialect, tuple(dict.fromkeys(earlier.symptoms + symptoms))
            )
    return Triage(intent, dialect, symptoms)


def _intent(text: str, symptoms: tuple[str, ...]) -> Intent:
    if _INTERACTION.search(text):
        return Intent.INTERACTION
    if _DRUG_SAFETY.search(text):
        return Intent.DRUG_SAFETY
    if _TREATMENT_REQUEST.search(text) and (symptoms or not _DRUG_INFO.search(text)):
        return Intent.SYMPTOM_TREATMENT
    if _DRUG_INFO.search(text):
        return Intent.DRUG_INFO
    return Intent.OTHER


def _symptoms(text: str) -> tuple[str, ...]:
    return tuple(name for name, rule in _SYMPTOMS if rule.search(text))


def _dialect(question: str, text: str) -> Dialect:
    if not _ARABIC_LETTER.search(question):
        return Dialect.ENGLISH
    egyptian = len(_EGYPTIAN.findall(text))
    saudi = len(_SAUDI.findall(text))
    return Dialect.EGYPTIAN if egyptian > saudi else Dialect.SAUDI


# ---- fixed replies and notes (Saudi: fixed strings the app shows are Saudi) ---------------------
RED_FLAG_REPLY = (
    "اللي تذكره ممكن يكون علامة على شي يحتاج كشف عاجل، وما ينفع نتعامل معه بدواء من الصيدلية. "
    "روح أقرب طوارئ الحين أو اتصل على 997، ولا تنتظر يخف بالمسكّن قبل ما يشوفك الطبيب."
)
SYMPTOM_WARNING = (
    "تنبيه: استشر الطبيب أو الصيدلي قبل ما تاخذ أي دواء، خصوصًا مع الحمل أو الرضاعة، أو مرض "
    "مزمن، أو أدوية ثانية تاخذها. هذي معلومات عامة وما تغني عن الكشف."
)
HEADACHE_RED_FLAGS_NOTE = (
    "روح الطوارئ فورًا أو اتصل على 997 إذا الصداع جاك فجأة وبقوة ما قد حسيت فيها، أو معه ضعف أو "
    "تنميل أو صعوبة في الكلام أو تغيّر في النظر، أو حرارة مع تيبّس في الرقبة، أو بعد ضربة على الراس."
)
NO_CLEARANCE_NOTE = (
    "(إذا ما لقينا شي مسجّل في مصادرنا فهذا ما يعني إنه آمن لك؛ الطبيب أو الصيدلي يقيّم حالتك.)"
)

# A sentence that calls a medicine or a combination safe, or says there is no interaction or no
# risk, is a clearance no source gives (CLAUDE.md: "no record" is never a safety verdict).
_CLEARANCE = _rx(
    r"\b(ب|و|ف)?(امن|امنه|امان)\b",
    r"\b(مفيش|مافيش|ما فيه|مافيه|مافي|ما في|لا يوجد|لا توجد|ليس هناك|مو فيه)\s+(اي\s+)?"
    r"(خطر|خطوره|مشكله|مشاكل|ضرر|تداخل|تداخلات|تعارض)\b",
    r"\bبدون (اي )?(خطر|مشاكل|مشكله|ضرر)\b",
    r"\b(is|are|it s|its|be|perfectly|completely|generally|totally)\s+safe\b",
    r"\bsafe to (take|use|combine|mix)\b",
    r"\bno (known )?(interactions?|risk|danger|problem)s?\b",
    r"\bwon t (interact|cause)\b|\bdoes not interact\b|\bdon t interact\b",
)
# ... unless it says the opposite, or only reports what a source records.
_QUALIFIED = _rx(
    r"\b(مش|غير|ليس|ليست|مو|ما هو|ما هي|مب)\s+(امن|امنه)\b",
    r"(ما يعني|لا يعني|مش معناه|مو معناه|ما معناه|ليس دليل|مش دليل|مو دليل|لا يثبت)",
    r"(مسجل|مسجله|مذكور|مذكوره|موثق|في المصدر|في المصادر|في مصادرنا|في قاعده|ddinter|medic|"
    r"السجل|النشره)",
    r"\b(not|isn t|aren t|un)\s*safe\b|\bnot (mean|proof|a guarantee|a clearance)\b",
    r"\b(recorded|documented|listed|found|reported)\b|\bin (our|the) (sources?|records?)\b",
)
_SENTENCES = re.compile(r"(?<=[!?؟؛\n])\s*|(?<=\.)\s+")


def gives_clearance(sentence: str) -> bool:
    text = normalize_text(sentence)
    return _CLEARANCE.search(text) is not None and _QUALIFIED.search(text) is None


def without_clearance(text: str) -> str:
    """The text without sentences that clear a medicine or a combination as safe, plus a note that
    no record is not a clearance. Text without such a sentence comes back unchanged."""
    sentences = [s for s in _SENTENCES.split(text) if s.strip()]
    kept = [s for s in sentences if not gives_clearance(s)]
    if len(kept) == len(sentences):
        return text
    rest = " ".join(s.strip() for s in kept).strip()
    return f"{rest}\n\n{NO_CLEARANCE_NOTE}" if rest else NO_CLEARANCE_NOTE


def finish(triage: Triage, text: str) -> str:
    """The answer after the rules for its kind of question: clearances removed for interaction
    and safety questions; for a treatment request, the urgent-signs note (headache) and the
    "consult a doctor first" warning, always, whatever the model wrote (owner, 2026-11-26)."""
    if triage.intent in (Intent.INTERACTION, Intent.DRUG_SAFETY, Intent.SYMPTOM_TREATMENT):
        text = without_clearance(text)
    if triage.intent is Intent.SYMPTOM_TREATMENT:
        notes = [SYMPTOM_WARNING]
        if "headache" in triage.symptoms:
            notes.insert(0, HEADACHE_RED_FLAGS_NOTE)
        missing = [note for note in notes if note not in text]
        if missing:
            text = "\n\n".join([text.rstrip(), *missing])
    return text
