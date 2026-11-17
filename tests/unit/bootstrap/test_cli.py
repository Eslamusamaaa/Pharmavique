import json
from pathlib import Path

import pytest

from pharmavique.bootstrap.cli import DEFAULT_USER_AGENT, build_parser, main
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore


def test_scrape_defaults_are_polite() -> None:
    args = build_parser().parse_args(["sfda-scrape"])

    assert args.delay >= 1.0
    assert args.out == "data/sfda"
    assert args.run_id is None
    assert args.max_pages is None
    assert args.enable_js is False
    assert args.headed is False


def test_default_user_agent_names_no_person_or_project() -> None:
    assert "pharmavique" not in DEFAULT_USER_AGENT.lower()
    assert "@" not in DEFAULT_USER_AGENT


def test_options_are_parsed() -> None:
    args = build_parser().parse_args(
        ["sfda-scrape", "--max-pages", "2", "--delay", "3", "--run-id", "r1"]
    )

    assert (args.max_pages, args.delay, args.run_id) == (2, 3.0, "r1")


def test_update_options_have_a_recheck_default() -> None:
    args = build_parser().parse_args(["sfda-update"])

    assert args.recheck > 0
    assert args.baseline is None


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def record(key: str, price: str) -> dict[str, object]:
    return {
        "key": key,
        "list": {"trade_name": f"T-{key}", "price": price},
        "en": [{"label": "Price", "value": price}],
        "ar": None,
        "provenance": {},
    }


def test_diff_command_prints_the_changes_between_two_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    SnapshotStore(tmp_path, "old").write_records([record("a", "1"), record("gone", "5")])
    SnapshotStore(tmp_path, "new").write_records([record("a", "2"), record("fresh", "7")])

    code = main(["sfda-diff", "old", "new", "--out", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "1 added, 1 removed, 1 changed" in out
    assert "T-a: 1 -> 2" in out


def test_update_without_any_baseline_explains_what_to_do(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["sfda-update", "--out", str(tmp_path)])

    assert code == 4
    assert "sfda-scrape" in capsys.readouterr().err


def test_update_uses_the_latest_pointer_to_find_the_baseline(tmp_path: Path) -> None:
    (tmp_path / "latest.json").write_text(json.dumps({"run_id": "empty"}), encoding="utf-8")

    # the pointed run has no records, so the command must refuse before touching the network
    assert main(["sfda-update", "--out", str(tmp_path)]) == 4


def test_load_needs_a_run_id() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["sfda-load"])


def test_load_options_are_parsed() -> None:
    args = build_parser().parse_args(
        ["sfda-load", "--run-id", "r1", "--batch-size", "50", "--limit", "10"]
    )

    assert (args.run_id, args.batch_size, args.limit) == ("r1", 50, 10)
