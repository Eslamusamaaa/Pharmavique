"""Read DDInter 2.0's downloadable CSV files (one per ATC group) into interaction records.

Columns: DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level. A pair appears in the file of either
drug's group, so the same pair can come twice (possibly rated differently): the higher rating wins.
"""

import csv
from pathlib import Path

from pharmavique.interactions.domain.names import normalize
from pharmavique.interactions.domain.records import InteractionRecord
from pharmavique.interactions.domain.severity import Severity

SOURCE = "ddinter-2.0"


def read_ddinter(folder: Path) -> list[InteractionRecord]:
    best: dict[tuple[str, str], Severity] = {}
    for path in sorted(folder.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                first, second = normalize(row.get("Drug_A", "")), normalize(row.get("Drug_B", ""))
                if not first or not second or first == second:
                    continue
                pair = (first, second) if first < second else (second, first)
                severity = Severity.from_source(row.get("Level", ""))
                if pair not in best or severity.rank > best[pair].rank:
                    best[pair] = severity
    return [InteractionRecord(a, b, severity, SOURCE) for (a, b), severity in sorted(best.items())]
