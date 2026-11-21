"""What the daily refresh did, read from its own summary and logs (never guessed)."""

import re
from dataclasses import dataclass
from datetime import date

_STEP = re.compile(r"^\|\s*([\w-]+)\s*\|\s*exit\s+(-?\d+)\s*\|\s*([\d.]+)\s*min\s*\|\s*$")
_REJECTED = re.compile(r"rejected=(\d+)")
_SKIPPED = re.compile(r"skipped \(no usable details\)=(\d+)")
_LOADED = re.compile(r"loaded (\d+) drugs")
OK_EXIT_CODES = {"lists-crawl": {0, 2}}  # the lists crawler exits 2 when a list finished with holes


@dataclass(frozen=True, slots=True)
class RefreshStep:
    name: str
    exit_code: int
    minutes: float

    @property
    def failed(self) -> bool:
        return self.exit_code not in OK_EXIT_CODES.get(self.name, {0})


@dataclass(frozen=True, slots=True)
class LoadCounts:
    """The drug loader's own report line: how many were loaded, skipped and rejected."""

    loaded: int | None
    skipped: int | None
    rejected: int | None


@dataclass(frozen=True, slots=True)
class RefreshDay:
    day: date
    steps: tuple[RefreshStep, ...]
    load: LoadCounts | None

    @property
    def failed_steps(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps if step.failed)


def parse_summary(text: str) -> tuple[RefreshStep, ...]:
    steps = []
    for line in text.lstrip("﻿").splitlines():
        match = _STEP.match(line.strip())
        if match:
            steps.append(RefreshStep(match[1], int(match[2]), float(match[3])))
    return tuple(steps)


def parse_load_log(text: str) -> LoadCounts:
    def first(pattern: re.Pattern[str]) -> int | None:
        match = pattern.search(text)
        return int(match[1]) if match else None

    return LoadCounts(first(_LOADED), first(_SKIPPED), first(_REJECTED))
