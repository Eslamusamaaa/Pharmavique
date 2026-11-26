"""What an answer is, and the response policy every answer keeps.

Owner's decision (2026-11-19): the assistant is helpful by default and firm only where there is
real danger.

- Registry facts (names, ingredients, strengths, prices, statuses) come from tools and are cited.
  General medicine information is allowed and is labelled as general, not as an SFDA record.
- Hard limits, checked in code after the model: no personal dose numbers or schedules, no
  telling someone to stop or switch a medicine on their own (saying "ask your doctor before
  stopping" is fine), and never "this is the right medicine for you".
- Owner's decision (2026-11-24): saying that an active ingredient may help symptoms like the
  person's, and that they may use a product with it, is allowed when the same sentence sends them
  to the doctor or pharmacist first.
- Emergencies get an immediate reply to call 997, without asking the model.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

NOT_IN_SOURCES = (
    "ما لقيت معلومة كافية أرد فيها على هذا السؤال. اسأل الصيدلي أو الطبيب، أو جرّب تكتب اسم الدواء."
)
RULE_REFUSAL = (
    "الجرعة المناسبة لك أو قرار إيقاف الدواء أو تغييره هذا قرار الطبيب أو الصيدلي، لأنه يعتمد على "
    "حالتك. أقدر أعرض لك بيانات الدواء الرسمية والنشرة ومصدرها."
)
DOSE_NOTE = "(الجرعة وطريقة الاستخدام المناسبة لك يحددها الطبيب أو الصيدلي.)"
SOURCES_DOWN = (
    "ما قدرت أوصل لبيانات الهيئة الحين، فما بجاوب بدونها عشان ما تكون المعلومة غلط. جرّب بعد شوي."
)
EMERGENCY_REPLY = (
    "هذا ممكن يكون موقف طارئ. اتصل بالإسعاف على 997 أو روح أقرب طوارئ فورًا، "
    "وخلك شايل علبة الدواء معك. لا تنتظر لين تظهر أعراض."
)


class Level(StrEnum):
    PATIENT = "patient"  # simple
    PHARMACIST = "pharmacist"  # for the pharmacist
    CLINICAL = "clinical"  # specialist


@dataclass(frozen=True, slots=True)
class Citation:
    source_id: (
        str  # "catalog:<register number>", "document:<chunk id>" or "interaction:<source>:..."
    )
    title: str
    url: str | None
    # "catalog", "document", "interaction", "contraindication", "sfda_site" (SFDA's drug list read
    # live from sfda.gov.sa) or "web" (unverified)
    kind: str
    published: str | None


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    citations: tuple[Citation, ...]
    level: Level
    grounded: bool  # at least one retrieved record is cited
    refused: bool = False  # the model's text crossed a hard limit and was replaced
    tools_used: tuple[str, ...] = ()
    general: bool = False  # an answer without registry citations: general information
    urgent: bool = False  # the question looked like an emergency
    # answered, web, general, emergency, red_flag, injection, rule_refusal, ungrounded,
    # sources_down or empty
    outcome: str = "answered"


# ---- emergencies (checked on the question, before any model call) --------------------------------
_EMERGENCY = re.compile(
    "|".join(
        f"(?:{rule})"
        for rule in (
            r"(بلعت|بلع|بلعت|شربت|شرب|أخدت|اخدت|أخذت|خدت)\s+.{0,25}"
            r"(علبة|العلبة|شريط|الشريط|زجاجة|الزجاجة|كله|كلها|كامل|كاملة|كتير|زيادة)",
            r"جرعة\s+(زائدة|زيادة)|overdose|swallowed\s+(the\s+)?(whole|all)",
            r"بالغلط|by\s+(mistake|accident)",
            r"ضيق\s+(تنفس|نفس|في\s+النفس)|مش\s+قادر\s+أتنفس|can'?t\s+breathe",
            r"تورم\s+في\s+(وشي|الوش|الوجه|شفايفي|لساني)|swelling\s+of\s+(the\s+)?(face|lips|tongue)",
            r"إغماء|اغمى|أغمى|فقد\s+الوعي|faint(ed)?|unconscious",
            r"تشنجات|seizure",
            r"(عايز|عاوز|أريد|اريد)\s+(أموت|اموت|انتحر|أنتحر)|انتحار|kill\s+myself|suicid",
        )
    ),
    re.IGNORECASE,
)


def is_emergency(question: str) -> bool:
    return _EMERGENCY.search(question) is not None


# ---- hard limits on the answer (checked after the model) -----------------------------------------
_DASH = "[-\u2010\u2011\u2012\u2013\u2014\u2212]"
_PER_UNIT = (
    r"(أقراص|اقراص|قرص|حبات|حبة|كبسولات|كبسولة|ملغ|ملجم|مجم|مل|غرام|جرام|جم|"
    r"tablets?|capsules?|mg|g|ml)"
)
_DOSE_RULES = (
    r"(خذ|خدي|خد|تناول|اشرب|استخدم)\s+(\d+|قرص|قرصين|حبة|حبتين|ملعقة|ملعقتين|كبسولة|نقطة)",
    r"(\d+|مرة|مرتين|ثلاث|تلات|أربع)\s*(مرات|مرة)\s*(في\s+)?(اليوم|يوميا|يوميًا|يومياً)",
    rf"كل\s*\d+(?:\s*{_DASH}\s*\d+)?\s*(ساعات|ساعة)",
    r"\btake\s+(\d+|one|two)\b",
    r"\b(\d+|once|twice|three)\s*(times\s+)?(a|per)\s+day\b",
    rf"\bevery\s+\d+(?:\s*{_DASH}\s*\d+)?\s+hours?\b",
    # an amount per day, per hours or per kilo: "8 أقراص في اليوم", "10 ملغ لكل كيلو"
    rf"\d+\s*{_PER_UNIT}\s*(في|كل|لكل|per|a|every)\s*(اليوم|يوم|ساعة|ساعات|كيلو|day|hours?|kg)",
    # a dose limit or usual dose followed by a number
    r"(الحد\s+الأقصى|الجرعة\s+(القصوى|المعتادة|الموصى\s+بها|المناسبة|اليومية)|لا\s+تتجاوز|"
    r"لا\s+يجوز\s+تجاوز|maximum\s+dose|usual\s+(adult\s+)?dose|do\s+not\s+exceed|"
    r"not\s+to\s+exceed).{0,40}\d",
)
# Saying which medicine a person should take for their symptom is a recommendation, not a fact.
_RECOMMEND_RULES = (
    r"(يمكنك|يمكنكِ|تقدر|تقدري|ممكن|يُفضَّل|يفضل|أنصحك|انصحك|أنصح|أوصي|يُنصح|ينصح)\s+"
    r"(ب|بأن\s+)?(أخذ|اخذ|تناول|تاخد|تاخذ|تتناول|تأخذ|تستخدم|استخدام|استعمال)"
    r"(?!\s+(ال)?(تطبيق|موقع|بحث))",
    r"\byou\s+(can|could|may|should)\s+(take|use)\b(?!\s+(the\s+)?(app|search))",
)
# Deciding for the person: this is their treatment, the best or the right medicine for them.
_FOR_YOU_RULES = (
    r"(هو|هي|هذا|هذه|ده|دي)\s+(ال)?(علاج|دواء|الدواء)\s*(ال)?(مناسب|الأنسب|أنسب|الصح)\s*(لك|ليك|لحالتك)",
    r"(أفضل|افضل|أحسن|احسن|أنسب|انسب)\s+(دواء|علاج)\s+(لك|ليك|لحالتك)",
    r"(هو|هي|هذا|ده)\s+(علاجك|دواك|دواءك)",
    r"\b(the\s+)?(right|best)\s+(medicine|treatment|drug)\s+for\s+you\b",
)
_STOP_SWITCH_RULES = (
    r"(توقف|توقّف|أوقف|اوقف|بطّل|بطل)\s+(عن\s+)?(تناول|أخذ|اخد|استخدام|الدواء|الدوا|دواء)",
    r"(استبدل|استبدله|استبدلها|بدّل|غيّر)\s*(ه|ها|الدواء|الدوا|دواء)?\s*(ب|إلى|الى)",  # noqa: RUF001
    r"\b(stop|discontinue|quit)\s+(taking|using)\b",
    r"\bswitch\s+(to|from)\b",
    r"\breplace\s+it\s+with\b",
)
# A sentence that sends the person to a doctor or pharmacist is guidance, not an instruction.
_CONSULT = re.compile(
    r"(اسأل|إسأل|تسأل|تسال|استشر|تستشير|استشارة|كلم|تكلم|راجع|تراجع)\s+(ال)?(دكتور|طبيب|الطبيب|صيدلي|الصيدلي|دكتورك|طبيبك)"
    r"|اتصل\s+بالطبيب|الطوارئ|ask\s+(your|a)\s+(doctor|pharmacist)|consult|call\s+your\s+doctor"
    r"|emergency",
    re.IGNORECASE,
)
_DOSE = re.compile("|".join(f"(?:{r})" for r in _DOSE_RULES), re.IGNORECASE)
_STOP_SWITCH = re.compile("|".join(f"(?:{r})" for r in _STOP_SWITCH_RULES), re.IGNORECASE)
_RECOMMEND = re.compile("|".join(f"(?:{r})" for r in _RECOMMEND_RULES), re.IGNORECASE)
_FOR_YOU = re.compile("|".join(f"(?:{r})" for r in _FOR_YOU_RULES), re.IGNORECASE)
# switching to another product is the doctor's or pharmacist's decision even with "ask" beside it
_SWITCH_TO = re.compile(
    r"(استبدل|استبدله|استبدلها|بدّل|بدل)\s*(ه|ها)?\s+\S+\s+(ب|إلى|الى)|\bswitch\s+to\b",  # noqa: RUF001
    re.IGNORECASE,
)
# sentence ends: a line break, ! ? ؟ ؛, or a full stop followed by a space (never inside 26.6)
_SENTENCES = re.compile(r"(?<=[!?؟؛\n])\s*|(?<=\.)\s+")


MIN_KEPT_CHARS = 40  # below this, what is left after removing sentences is not an answer

# What a medicine is used for is not in the registry record. A sentence that says it is general
# knowledge dressed in a registry citation, so it is removed unless a document or a web page was
# retrieved in the same run.
NO_USE_SOURCE_NOTE = (
    "(بيانات الهيئة التي لدينا لا يحدد فيها استخدامات الدواء؛ للاستخدامات راجع نشرة الدواء "
    "أو اسأل الصيدلي.)"
)
_USE_CLAIM = re.compile(
    r"(يُستخدم|يستخدم|يُستعمل|يستعمل|تُستخدم|تستخدم|يعالج|يُعالج|يُوصف\s+ل|يُعطى\s+لعلاج)"
    r"\s+(عادة|عادةً|غالبا|غالباً)?\s*(ل|في|بـ)"
    r"|(ل|ل?ل)(تخفيف|تسكين|علاج|خفض|منع|تقليل)\s"
    r"|\b(is|are)\s+(commonly\s+|usually\s+|generally\s+)?used\s+(to|for)\b"
    r"|\bindicated\s+for\b|\bused\s+to\s+treat\b",
    re.IGNORECASE,
)


def states_a_use(sentence: str) -> bool:
    return _USE_CLAIM.search(sentence) is not None


def without_unsupported_use_claims(text: str) -> str | None:
    """The text without the sentences that say what a medicine is used for, plus a note that our
    data does not state it. Text with no such sentence is returned unchanged."""
    sentences = [s for s in _SENTENCES.split(text) if s.strip()]
    kept = [s for s in sentences if not states_a_use(s)]
    if len(kept) == len(sentences):
        return text
    rest = " ".join(s.strip() for s in kept).strip()
    return f"{rest}\n\n{NO_USE_SOURCE_NOTE}" if rest else NO_USE_SOURCE_NOTE


def _breaks(sentence: str) -> bool:
    if _DOSE.search(sentence) or _FOR_YOU.search(sentence) or _SWITCH_TO.search(sentence):
        return True
    consult = bool(_CONSULT.search(sentence))
    if _RECOMMEND.search(sentence) and not consult:
        return True  # "you may take X" only with the doctor or pharmacist asked first
    return bool(_STOP_SWITCH.search(sentence)) and not consult


def without_rule_breaking_sentences(text: str) -> str | None:
    """The text without the sentences that break a rule, with a short note; None when what
    is left is too short to stand as an answer. Unchanged text is returned as it is."""
    sentences = [s for s in _SENTENCES.split(text) if s.strip()]
    kept = [s for s in sentences if not _breaks(s)]
    if len(kept) == len(sentences):
        return text
    rest = " ".join(s.strip() for s in kept).strip()
    if len(rest) < MIN_KEPT_CHARS:
        return None
    return f"{rest}\n\n{DOSE_NOTE}"


def breaks_rules(text: str) -> bool:
    """True when the text gives a personal dose instruction, or tells someone to stop or switch a
    medicine without sending them to a doctor or pharmacist in the same sentence."""
    if _DOSE.search(text):
        return True
    return any(_breaks(sentence) for sentence in _SENTENCES.split(text))
