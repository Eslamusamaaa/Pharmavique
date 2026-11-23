from pharmavique.offers.domain.lifecycle import (
    RunOutcome,
    UnseenListing,
    baseline,
    classify_run,
    gone_confirmed,
    plan_missing,
    should_pause,
    status_after_seen,
)
from pharmavique.offers.domain.model import ListingStatus, RunStatus


def run(
    seen: int = 1000, *, finished: bool = True, blocked: bool = False, errors: int = 0
) -> RunOutcome:
    return RunOutcome(finished, blocked, errors, seen)


def test_a_finished_clean_run_with_enough_urls_is_complete() -> None:
    assert classify_run(run(900), 1000) is RunStatus.COMPLETE


def test_a_run_below_85_percent_of_the_baseline_is_partial() -> None:
    assert classify_run(run(849), 1000) is RunStatus.PARTIAL
    assert classify_run(run(850), 1000) is RunStatus.COMPLETE


def test_a_run_that_did_not_finish_or_had_an_unhandled_error_is_partial() -> None:
    assert classify_run(run(finished=False), None) is RunStatus.PARTIAL
    assert classify_run(run(errors=1), None) is RunStatus.PARTIAL


def test_a_block_is_blocked_and_nothing_seen_is_failed() -> None:
    assert classify_run(run(blocked=True), None) is RunStatus.BLOCKED
    assert classify_run(run(0, finished=False), None) is RunStatus.FAILED


def test_the_first_run_has_no_baseline_and_is_complete_when_clean() -> None:
    assert classify_run(run(10), None) is RunStatus.COMPLETE


def test_the_baseline_is_the_median_of_the_last_five_complete_runs() -> None:
    assert baseline([]) is None
    assert baseline([100, 120, 90, 110, 105, 5, 6]) == 90  # the last five: 90, 110, 105, 5, 6
    assert baseline([100, 200, 300]) == 200


def test_nothing_changes_after_a_run_that_is_not_complete() -> None:
    for status in (RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.BLOCKED):
        plan = plan_missing([UnseenListing(1, 1)], 1000, status)

        assert plan.mark_missing == ()
        assert plan.increment == ()
        assert not plan.held


def test_a_listing_is_missing_only_after_two_complete_runs_in_a_row() -> None:
    first = plan_missing([UnseenListing(1, 0)], 1000, RunStatus.COMPLETE)
    second = plan_missing([UnseenListing(1, 1)], 1000, RunStatus.COMPLETE)

    assert first.increment == (1,)
    assert first.mark_missing == ()
    assert second.mark_missing == (1,)


def test_too_many_missing_at_once_is_held_for_review() -> None:
    unseen = [UnseenListing(i, 1) for i in range(200)]

    plan = plan_missing(unseen, 5000, RunStatus.COMPLETE)  # cap: max(50, 2 percent = 100)

    assert plan.held
    assert plan.mark_missing == ()
    assert len(plan.increment) == 200


def test_up_to_the_cap_is_marked() -> None:
    unseen = [UnseenListing(i, 1) for i in range(100)]

    plan = plan_missing(unseen, 5000, RunStatus.COMPLETE)

    assert not plan.held
    assert len(plan.mark_missing) == 100


def test_a_small_retailer_still_allows_fifty() -> None:
    unseen = [UnseenListing(i, 1) for i in range(50)]

    assert not plan_missing(unseen, 800, RunStatus.COMPLETE).held


def test_a_listing_seen_again_comes_back_with_the_page_saying_whether_it_can_be_bought() -> None:
    assert status_after_seen(ListingStatus.MISSING, True) is ListingStatus.ACTIVE
    assert status_after_seen(ListingStatus.ACTIVE, False) is ListingStatus.UNAVAILABLE
    assert status_after_seen(ListingStatus.UNAVAILABLE, True) is ListingStatus.ACTIVE
    assert status_after_seen(ListingStatus.DISCONTINUED, None) is ListingStatus.ACTIVE


def test_a_listing_is_discontinued_only_when_its_own_url_is_gone_in_two_runs() -> None:
    assert not gone_confirmed(1)
    assert gone_confirmed(2)


def test_three_failures_in_a_row_or_any_block_pause_the_retailer() -> None:
    assert not should_pause(2, blocked=False)
    assert should_pause(3, blocked=False)
    assert should_pause(0, blocked=True)
