"""What a scan of a box or a prescription produces (AI_ARCHITECTURE.md section 4).

Rules: every line needs review by a person (nothing is auto-confirmed); a prescription's dose or
instructions are never read into a value: they are always "غير واضح" for the pharmacist to
confirm (owner's decision and CLAUDE.md: no dosing). The image itself is never part of a result.
A line whose name is not matched with confidence is marked `uncertain`: the app then asks the person
to confirm among the closest names or to retake the photo, instead of guessing.
"""

from dataclasses import dataclass
from enum import StrEnum

UNCLEAR_DOSE = "غير واضح"
MAX_LINES = 15
MAX_SHELF_LINES = 40  # a shelf photo holds many boxes; every one still needs review
# A line is "confident" when the registry name that matches best scores at least this much (the
# name score runs from 0 to 1: a name printed exactly scores about 0.95 or more, one misspelled
# letter about 0.7, an unrelated word 0.5 at most; probed on 2026-11-25 with typed names, not
# photos). Not yet tuned on real photos: `scripts/scan_eval.py` prints the trade-off to choose it.
DEFAULT_MIN_SCORE = 0.9


class ScanKind(StrEnum):
    BOX = "box"
    PRESCRIPTION = "prescription"
    SHELF = "shelf"  # many boxes in one photo, for a pharmacist to confirm one by one


@dataclass(frozen=True, slots=True)
class ExtractedLine:
    """One medicine as the vision model read it: the raw line, the name, strength and form."""

    raw_text: str
    name: str
    strength: str | None
    form: str | None

    def query(self) -> str:
        """What is searched in the registry: the name with its strength when read."""
        return " ".join(part for part in (self.name, self.strength) if part).strip()


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    register_number: str
    trade_name_ar: str | None
    trade_name_en: str | None
    score: float


class LineConfidence(StrEnum):
    CONFIDENT = "confident"
    UNCERTAIN = "uncertain"


def assess(candidates: tuple[MatchCandidate, ...], min_score: float) -> LineConfidence:
    """Confident only when there is a candidate and the best name match reaches `min_score`."""
    if not candidates:
        return LineConfidence.UNCERTAIN
    best = max(candidate.score for candidate in candidates)
    return LineConfidence.CONFIDENT if best >= min_score else LineConfidence.UNCERTAIN


@dataclass(frozen=True, slots=True)
class LineResult:
    line: ExtractedLine
    candidates: tuple[MatchCandidate, ...]
    dose: str | None  # UNCLEAR_DOSE on prescriptions, None on boxes; never a read value
    needs_review: bool = True  # always true: a person confirms every line
    confidence: LineConfidence = LineConfidence.UNCERTAIN  # the safe default


@dataclass(frozen=True, slots=True)
class ScanResult:
    kind: ScanKind
    lines: tuple[LineResult, ...]

    @property
    def status(self) -> str:
        return "needs_review" if self.lines else "nothing_read"
