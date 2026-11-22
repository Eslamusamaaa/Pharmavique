"""What an answer is, and the response policy every answer keeps.

Owner's decision (2026-11-19): the assistant is helpful by default and firm only where there is
real danger.

- Registry facts (names, ingredients, strengths, prices, statuses) come from tools and are cited.
  General medicine information is allowed and is labelled as general, not as an SFDA record.
- Hard limits, checked in code after the model: no personal dose numbers or schedules, and no
  telling someone to stop or switch a medicine on their own (saying "ask your doctor before
  stopping" is fine). Emergencies get an immediate reply to call 997, without asking the model.
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
    kind: str  # "catalog", "document" or "interaction"
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
    # answered, general, emergency, injection, rule_refusal, ungrounded, sources_down or empty
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
_DOSE_RULES = (
    r"(خذ|خدي|خد|تناول|اشرب|استخدم)\s+(\d+|قرص|قرصين|حبة|حبتين|ملعقة|ملعقتين|كبسولة|نقطة)",
    r"(\d+|مرة|مرتين|ثلاث|تلات|أربع)\s*(مرات|مرة)\s*(في\s+)?(اليوم|يوميا|يوميًا|يومياً)",
    r"كل\s+\d+\s*(ساعات|ساعة)",
    r"\btake\s+(\d+|one|two)\b",
    r"\b(\d+|once|twice|three)\s*(times\s+)?(a|per)\s+day\b",
    r"\bevery\s+\d+\s+hours?\b",
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
    r"(اسأل|إسأل|استشر|استشارة|كلم|راجع)\s+(ال)?(دكتور|طبيب|الطبيب|صيدلي|الصيدلي|دكتورك|طبيبك)"
    r"|اتصل\s+بالطبيب|الطوارئ|ask\s+your\s+(doctor|pharmacist)|consult|call\s+your\s+doctor"
    r"|emergency",
    re.IGNORECASE,
)
_DOSE = re.compile("|".join(f"(?:{r})" for r in _DOSE_RULES), re.IGNORECASE)
_STOP_SWITCH = re.compile("|".join(f"(?:{r})" for r in _STOP_SWITCH_RULES), re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?؟؛\n])\s*")


MIN_KEPT_CHARS = 40  # below this, what is left after removing sentences is not an answer


def _breaks(sentence: str) -> bool:
    if _DOSE.search(sentence):
        return True
    return bool(_STOP_SWITCH.search(sentence)) and not _CONSULT.search(sentence)


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
    return any(
        _STOP_SWITCH.search(sentence) and not _CONSULT.search(sentence)
        for sentence in _SENTENCES.split(text)
    )
