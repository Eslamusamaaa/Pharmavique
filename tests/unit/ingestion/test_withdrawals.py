"""When a drug that left the SFDA list may be withdrawn from the catalog (pure rule, no I/O)."""

from pharmavique.ingestion.application.withdrawals import plan_withdrawals


def plan(
    listed: set[str],
    seen_now: set[str],
    seen_before: set[str],
    *,
    clean: bool = True,
    cap: int = 50,
):
    return plan_withdrawals(
        listed=listed,
        seen_now=seen_now,
        seen_before=seen_before,
        run_is_clean=clean,
        max_withdrawals=cap,
    )


def test_a_drug_missing_for_the_first_time_is_only_pending() -> None:
    result = plan(listed={"a", "b"}, seen_now={"a"}, seen_before={"a", "b"})

    assert result.to_withdraw == ()
    assert result.pending == ("b",)
    assert result.blocked_reason is None


def test_a_drug_missing_in_two_runs_in_a_row_is_withdrawn() -> None:
    result = plan(listed={"a", "b"}, seen_now={"a"}, seen_before={"a"})

    assert result.to_withdraw == ("b",)
    assert result.pending == ()


def test_nothing_is_withdrawn_when_the_run_was_not_complete() -> None:
    result = plan(listed={"a", "b"}, seen_now={"a"}, seen_before={"a"}, clean=False)

    assert result.to_withdraw == ()
    assert result.blocked_reason is not None
    assert "complete" in result.blocked_reason


def test_a_drug_that_is_seen_again_is_never_a_candidate() -> None:
    result = plan(listed={"a", "b"}, seen_now={"a", "b"}, seen_before={"a"})

    assert result.to_withdraw == ()
    assert result.pending == ()


def test_too_many_at_once_withdraws_nothing_and_says_why() -> None:
    listed = {f"d{i}" for i in range(10)}

    result = plan(listed=listed, seen_now=set(), seen_before=set(), cap=5)

    assert result.to_withdraw == ()
    assert result.blocked_reason is not None
    assert "10" in result.blocked_reason
    assert "5" in result.blocked_reason


def test_exactly_the_cap_is_allowed_and_the_result_is_sorted() -> None:
    result = plan(listed={"c", "a", "b"}, seen_now=set(), seen_before=set(), cap=3)

    assert result.to_withdraw == ("a", "b", "c")
    assert result.blocked_reason is None


def test_drugs_not_listed_in_the_catalog_are_ignored() -> None:
    # already withdrawn (not in `listed`) or never loaded: nothing to do for them
    result = plan(listed={"a"}, seen_now={"a"}, seen_before={"a", "gone"})

    assert result.to_withdraw == ()
    assert result.pending == ()
