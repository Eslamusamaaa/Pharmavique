"""How serious a recorded interaction is, as the source rates it."""

from enum import StrEnum


class Severity(StrEnum):
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"
    UNKNOWN = "unknown"  # the source records an interaction but rates none

    @property
    def rank(self) -> int:
        return _RANK[self]

    @classmethod
    def from_source(cls, text: str) -> "Severity":
        """The source's own word, case-insensitive; anything unrecognized is `unknown`."""
        try:
            return cls(text.strip().lower())
        except ValueError:
            return cls.UNKNOWN


_RANK = {Severity.MAJOR: 3, Severity.MODERATE: 2, Severity.MINOR: 1, Severity.UNKNOWN: 0}
