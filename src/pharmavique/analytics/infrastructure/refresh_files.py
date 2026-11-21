"""Reads the daily refresh's own output folders (`data/refresh/<yyyymmdd>/summary.md`)."""

from datetime import date, datetime
from pathlib import Path

from pharmavique.analytics.domain.refresh import (
    RefreshDay,
    parse_load_log,
    parse_summary,
)


def _read(path: Path) -> str | None:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except (OSError, UnicodeError):
            continue
    return None


class FileRefreshHistory:
    """The last refresh days, newest first. An empty list when the folder does not exist (for
    example inside a container that never ran the refresh), which is not the same as "all fine"."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def recent(self, count: int) -> list[RefreshDay]:
        if not self._root.is_dir():
            return []
        days: list[RefreshDay] = []
        for folder in sorted(self._root.iterdir(), reverse=True):
            try:
                day = datetime.strptime(folder.name, "%Y%m%d").date()
            except ValueError:
                continue
            days.append(self._day(folder, day))
            if len(days) == count:
                break
        return days

    @staticmethod
    def _day(folder: Path, day: date) -> RefreshDay:
        summary = _read(folder / "summary.md")
        load = _read(folder / "drugs-load.log")
        return RefreshDay(
            day=day,
            steps=parse_summary(summary) if summary else (),
            load=parse_load_log(load) if load else None,
        )
