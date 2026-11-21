"""Reading the daily refresh's summary and load log."""

from datetime import date
from pathlib import Path

from pharmavique.analytics.domain.refresh import parse_load_log, parse_summary
from pharmavique.analytics.infrastructure.refresh_files import FileRefreshHistory

SUMMARY = """﻿# Daily refresh 20261121

| step | result | time |
|---|---|---|
| drugs-update | exit 3 | 20.9 min |
| lists-crawl | exit 2 | 4.5 min |
| drugs-load | exit 0 | 1.0 min |
"""
LOAD = (
    "loaded 9162 drugs in 5 batches: added=3 relisted=0 details_changed=10 "
    "price_changed=2 unchanged=9147\n"
    "skipped (no usable details)=4 rejected=7 records with unreadable values kept as text=1\n"
)


def test_the_summary_table_is_read_step_by_step() -> None:
    steps = parse_summary(SUMMARY)
    assert [(s.name, s.exit_code, s.minutes) for s in steps] == [
        ("drugs-update", 3, 20.9),
        ("lists-crawl", 2, 4.5),
        ("drugs-load", 0, 1.0),
    ]


def test_the_lists_crawler_exit_2_is_not_a_failure_but_exit_3_is() -> None:
    failed = [s.name for s in parse_summary(SUMMARY) if s.failed]
    assert failed == ["drugs-update"]


def test_the_load_log_gives_loaded_skipped_and_rejected() -> None:
    load = parse_load_log(LOAD)
    assert (load.loaded, load.skipped, load.rejected) == (9162, 4, 7)


def test_a_log_without_the_report_gives_none_not_zero() -> None:
    load = parse_load_log("nothing useful here")
    assert (load.loaded, load.skipped, load.rejected) == (None, None, None)


def test_recent_days_come_newest_first_and_skip_odd_folders(tmp_path: Path) -> None:
    for name in ("20261119", "20261121", "notes", "20261120"):
        (tmp_path / name).mkdir()
    (tmp_path / "20261121" / "summary.md").write_text(SUMMARY, encoding="utf-8")
    (tmp_path / "20261121" / "drugs-load.log").write_text(LOAD, encoding="utf-8")
    days = FileRefreshHistory(tmp_path).recent(2)
    assert [d.day for d in days] == [date(2026, 11, 21), date(2026, 11, 20)]
    assert days[0].failed_steps == ("drugs-update",)
    assert days[0].load is not None
    assert days[0].load.rejected == 7
    assert days[1].steps == ()
    assert days[1].load is None


def test_a_missing_folder_gives_no_days(tmp_path: Path) -> None:
    assert FileRefreshHistory(tmp_path / "absent").recent(5) == []
