import pytest

from pharmavique.bootstrap.cli import DEFAULT_USER_AGENT, build_parser


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


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
