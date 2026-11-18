"""What an answer is, and the rules every answer must keep (CLAUDE.md, PHASE_2_PLAN 3).

- Answers come only from retrieved records (catalog, official documents) and cite them; with no
  source, the answer says so instead of guessing.
- Never medical advice: no dosing, never "stop" or "switch". The pharmacist or doctor decides.
These checks are deliberately strict: a blocked fact is better than a dangerous instruction.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

NOT_IN_SOURCES = (
    "مش لاقي إجابة السؤال ده في مصادرنا الرسمية (سجل هيئة الغذاء والدواء ونشراتها). "
    "اسأل الصيدلي أو الطبيب."
)
RULE_REFUSAL = (
    "مقدرش أدي تعليمات عن الجرعة أو إيقاف الدواء أو تغييره. ده قرار الصيدلي أو الطبيب. "
    "أقدر أعرض لك بيانات الدواء الرسمية ومصدرها."
)


class Level(StrEnum):
    PATIENT = "patient"  # مبسّط
    PHARMACIST = "pharmacist"  # للصيدلي
    CLINICAL = "clinical"  # متخصص


@dataclass(frozen=True, slots=True)
class Citation:
    source_id: str  # "catalog:<register number>" or "document:<chunk id>"
    title: str
    url: str | None
    kind: str  # "catalog" or "document"
    published: str | None


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    citations: tuple[Citation, ...]
    level: Level
    grounded: bool  # at least one source was retrieved and cited
    refused: bool = False  # the model's text broke a rule and was replaced
    tools_used: tuple[str, ...] = ()


_RULES = [
    # stop / switch, Arabic (Egyptian and standard) and English
    r"(توقف|توقّف|أوقف|اوقف|بطّل|بطل)\s+(عن\s+)?(تناول|أخذ|اخد|استخدام|الدواء|الدوا)",
    r"(استبدل|استبدله|استبدلها|بدّل|بدل|غيّر|غير)\s+(ه|ها|الدواء|الدوا|دواء)?\s*(ب|إلى|الى|لـ)",  # noqa: RUF001
    r"\b(stop|discontinue|quit)\s+(taking|using|the)\b",
    r"\bswitch\s+(to|from)\b",
    r"\breplace\s+it\s+with\b",
    # dosing instructions: "take N", "N times a day", "every N hours"
    r"(خذ|خدي|خد|تناول|اشرب|استخدم)\s+(\d+|قرص|قرصين|حبة|حبتين|ملعقة|ملعقتين|كبسولة|نقطة)",
    r"(\d+|مرة|مرتين|ثلاث|تلات|أربع)\s*(مرات|مرة)\s*(في\s+)?(اليوم|يوميا|يوميًا|يومياً)",
    r"كل\s+\d+\s*(ساعات|ساعة)",
    r"\btake\s+(\d+|one|two|a|an)\b",
    r"\b(\d+|once|twice|three)\s*(times\s+)?(a|per)\s+day\b",
    r"\bevery\s+\d+\s+hours?\b",
]
_PATTERN = re.compile("|".join(f"(?:{rule})" for rule in _RULES), re.IGNORECASE)


def breaks_rules(text: str) -> bool:
    """True when the text gives a dose instruction or tells someone to stop or switch."""
    return _PATTERN.search(text) is not None
