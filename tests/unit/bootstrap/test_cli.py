import json
from pathlib import Path

import httpx
import pytest

from pharmavique.bootstrap.cli import DEFAULT_USER_AGENT, _load_robots, build_parser, main
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
    assert args.from_records is False


def test_load_can_read_the_records_file_instead_of_the_pages() -> None:
    args = build_parser().parse_args(["sfda-load", "--run-id", "r1", "--from-records"])

    assert args.from_records is True


def test_lists_defaults_skip_the_giants_and_stay_polite() -> None:
    args = build_parser().parse_args(["sfda-lists"])

    assert args.out == "data/lists"
    assert args.include_giant is False
    assert args.delay >= 1.0


def test_lists_show_prints_every_known_list_without_network(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["sfda-lists", "--show"]) == 0

    out = capsys.readouterr().out
    assert "drug-shortage" in out
    assert out.count("giant") == 3


def test_lists_with_an_unknown_name_says_which_names_exist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["sfda-lists", "--lists", "nope"]) == 4

    assert "unknown list" in capsys.readouterr().err


async def test_robots_download_is_retried_after_a_connection_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("reset", request=request)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")

    async def no_sleep(_: float) -> None:
        return None

    policy = await _load_robots(
        "https://example.test",
        "agent",
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
    )

    assert attempts == 3
    assert policy.allows("https://example.test/public")
    assert not policy.allows("https://example.test/private")


def test_knowledge_embed_options_are_parsed() -> None:
    args = build_parser().parse_args(["knowledge-embed", "--batch-size", "16", "--limit", "100"])

    assert (args.command, args.batch_size, args.limit) == ("knowledge-embed", 16, 100)


def test_knowledge_embed_defaults() -> None:
    args = build_parser().parse_args(["knowledge-embed"])

    assert (args.batch_size, args.limit) == (32, None)


def test_verify_account_parses_a_rejection_with_its_reason() -> None:
    args = build_parser().parse_args(
        ["verify-account", "--email", "p@example.com", "--reject", "--note", "no licence"]
    )
    assert (args.command, args.email, args.reject, args.note) == (
        "verify-account",
        "p@example.com",
        True,
        "no licence",
    )


def test_verify_account_verifies_by_default() -> None:
    args = build_parser().parse_args(["verify-account", "--email", "p@example.com"])
    assert args.reject is False
    assert args.note is None


def test_the_load_can_be_limited_to_what_changed_since_the_last_loaded_run() -> None:
    args = build_parser().parse_args(
        [
            "sfda-load",
            "--run-id",
            "update-20261127",
            "--from-records",
            "--changed-since",
            "update-20261126",
        ]
    )
    assert args.changed_since == "update-20261126"
    assert build_parser().parse_args(["sfda-load", "--run-id", "x"]).changed_since is None
