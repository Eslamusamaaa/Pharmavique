"""What a scan of a box or a prescription produces (AI_ARCHITECTURE.md section 4).

Rules: every line needs review by a person (nothing is auto-confirmed); a prescription's dose or
instructions are never read into a value: they are always "غير واضح" for the pharmacist to
confirm (owner's decision and CLAUDE.md: no dosing). The image itself is never part of a result.
"""

from dataclasses import dataclass
from enum import StrEnum

UNCLEAR_DOSE = "غير واضح"
MAX_LINES = 15


class ScanKind(StrEnum):
    BOX = "box"
    PRESCRIPTION = "prescription"


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


@dataclass(frozen=True, slots=True)
class LineResult:
    line: ExtractedLine
    candidates: tuple[MatchCandidate, ...]
    dose: str | None  # UNCLEAR_DOSE on prescriptions, None on boxes; never a read value
    needs_review: bool = True


@dataclass(frozen=True, slots=True)
class ScanResult:
    kind: ScanKind
    lines: tuple[LineResult, ...]

    @property
    def status(self) -> str:
        return "needs_review" if self.lines else "nothing_read"
