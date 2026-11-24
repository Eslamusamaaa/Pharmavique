"""Guardrails around the model: what may go in, and what may come out.

In: questions that try to manipulate the assistant (override its rules, reveal its prompt, make
it role-play without limits) are answered with a fixed reply and never reach the model. These
rules are deterministic; a learned classifier can add to them (an `InjectionDetector` adapter),
because such classifiers are weak in Arabic.

Out: a drug's facts must come from tools. Every number written with a medicine unit or a currency,
and every 10-digit register number, must appear in what the tools returned in this run; otherwise
the answer is withheld instead of shown with an invented fact.
"""

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

INJECTION_REPLY = (
    "أنا هنا عشان أساعدك في معلومات الأدوية من مصادرها الرسمية، وما أقدر أغيّر قواعدي أو أعرض "
    "تعليماتي الداخلية. اسألني عن أي دواء."
)
UNGROUNDED_REPLY = (
    "ما قدرت أتأكد من كل الأرقام في الإجابة من مصادرنا، فما بعرضها عشان ما تكون غلط. "
    "افتح صفحة الدواء للبيانات الرسمية، أو اسأل الصيدلي."
)

_INJECTION_RULES = (
    # English
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|rules?|prompt|guidelines|"
    r"restrictions|above|previous|prior)\b",
    r"\b(system|hidden|initial|secret)\s+(prompt|instructions?|message)\b",
    r"\b(reveal|print|show|repeat|leak)\b.{0,30}\b(prompt|instructions?|rules)\b",
    r"\byou\s+are\s+now\b|\bact\s+as\b.{0,30}\b(no|without)\s+(limits|restrictions|rules)\b",
    r"\b(pretend|role-?play)\b.{0,60}\b(no|without)\s+(limits|restrictions|rules|filters)\b",
    r"\bjailbreak\b|\bDAN\b|developer\s+mode",
    # Arabic (standard and Egyptian/Saudi)
    r"(تجاهل|انسى|انس|إنسى|اتجاهل|تخطى|تخطّى|الغي|ألغِ)\s+.{0,25}(التعليمات|القواعد|الأوامر|البرومبت)",
    r"(برومبت|البرومبت|السيستم\s*برومبت|التعليمات\s+(السرية|الداخلية|المخفية))",
    r"(اعرض|اكتب|قولي|وريني|اطبع)\s+.{0,15}(تعليماتك|التعليمات\s+بتاعتك|قواعدك)",
    r"(اعتبر|تخيل|تخيّل)\s+(نفسك|انك|إنك).{0,40}(بدون|من\s+غير)\s+(قيود|قواعد|حدود)",
)
_INJECTION = re.compile("|".join(f"(?:{rule})" for rule in _INJECTION_RULES), re.IGNORECASE)


def looks_like_injection(question: str) -> bool:
    return _INJECTION.search(question) is not None


# ---- grounding of numbers ---------------------------------------------------------------------
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")  # noqa: RUF001
_UNITS = r"mg|mcg|µg|g|ml|iu|%|ملجم|مجم|ملغ|مغ|ميكروجرام|جم|جرام|مل|وحدة|ريال|SAR|SR|ر\.س"
_WITH_UNIT = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNITS})(?![A-Za-z])", re.IGNORECASE)
_REGISTER = re.compile(r"(?<!\d)(\d{10})(?!\d)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _canonical(number: str) -> str:
    try:
        value = Decimal(number)
    except InvalidOperation:
        return number
    text = format(value.normalize(), "f")
    return text.rstrip(".") if "." in text else text


# "31. 65 ريال": some models put a space after the decimal point. Joined only when a unit or a
# currency follows and the first number does not start a line (a numbered list item: "1. 5 mg").
_SPACED_DECIMAL = re.compile(rf"(\d+)\.\s+(\d+)(?=\s*(?:{_UNITS})(?![A-Za-z]))", re.IGNORECASE)


def tidy_numbers(text: str) -> str:
    def join(match: re.Match[str]) -> str:
        line_start = text.rfind("\n", 0, match.start()) + 1
        if not text[line_start : match.start()].strip(" \t-*•"):
            return match.group(0)  # a list number, not a decimal
        return f"{match.group(1)}.{match.group(2)}"

    return _SPACED_DECIMAL.sub(join, text)


UNGROUNDED_NOTE = (
    "(شلت أرقام ما قدرت أتأكد منها من مصادرنا؛ اسأل الصيدلي عنها أو افتح صفحة الدواء.)"
)
_MIN_KEPT_CHARS = 40  # below this, what is left is not an answer
# Sentence ends: a line break, ! ? ؟ ؛, or a full stop followed by a space (never inside 26.6).
_SENTENCE_ENDS = re.compile(r"(?<=[!?؟؛\n])[ \t]*|(?<=\.)[ \t]+")


def without_ungrounded_sentences(answer: str, evidence: Sequence[str]) -> str | None:
    """The answer without the sentences (or list lines) that hold a number no tool returned, plus
    a short note; None when what is left is too short to stand as an answer."""
    pieces = _SENTENCE_ENDS.split(answer)
    kept = [p for p in pieces if not ungrounded_facts(p, evidence)]
    if len(kept) == len(pieces):
        return answer
    joined = "".join(
        piece if i == 0 or kept[i - 1].endswith("\n") else f" {piece}"
        for i, piece in enumerate(kept)
    )
    rest = re.sub(r"\n{3,}", "\n\n", joined).strip()
    if len(rest) < _MIN_KEPT_CHARS:
        return None
    return f"{rest}\n\n{UNGROUNDED_NOTE}"


def ungrounded_facts(answer: str, evidence: Sequence[str]) -> list[str]:
    """Numbers with a medicine unit or currency, and register numbers, that no tool returned."""
    text = answer.translate(_ARABIC_DIGITS)
    raw = [n for item in evidence for n in _NUMBER.findall(item.translate(_ARABIC_DIGITS))]
    known = {_canonical(n) for n in raw} | set(raw)  # raw keeps leading zeros of register numbers
    missing: list[str] = []
    for match in _WITH_UNIT.finditer(text):
        number, unit = match.group(1), match.group(2)
        if _canonical(number) not in known:
            missing.append(f"{number} {unit}")
    for match in _REGISTER.finditer(text):
        if match.group(1) not in known:
            missing.append(match.group(1))
    return missing
