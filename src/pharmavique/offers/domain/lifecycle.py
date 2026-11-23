"""When a listing is missing, when a run can be trusted, when a retailer must stop.

A failed or partial crawl changes nothing: a listing is never marked missing because we could not
see it. Same spirit as the SFDA withdrawal rule (two complete runs in a row, a cap per run).
The numbers are starting values, tuned from the pilot (decision D-9).
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from pharmavique.offers.domain.model import ListingStatus, RunStatus

MIN_COMPLETENESS = 0.85  # share of the retailer's baseline a complete run must see
BASELINE_RUNS = 5
MISSING_AFTER_RUNS = 2
MISSING_CAP_SHARE = 0.02
MISSING_CAP_MINIMUM = 50
DISCONTINUED_AFTER_RUNS = 2
PAUSE_AFTER_FAILURES = 3


@dataclass(frozen=True, slots=True)
class RunOutcome:
    enumeration_finished: bool  # every sitemap file and category page was read
    blocked: bool  # a 401, 403 or 429 (never retried)
    unhandled_errors: int
    urls_seen: int


@dataclass(frozen=True, slots=True)
class UnseenListing:
    id: int
    missed_runs: int  # complete runs in a row in which it was not seen


@dataclass(frozen=True, slots=True)
class MissingPlan:
    mark_missing: tuple[int, ...]
    increment: tuple[int, ...]  # listings whose missed-run counter goes up by one
    held: bool  # too many at once: a person looks before anything is marked


def baseline(complete_run_counts: Sequence[int]) -> int | None:
    """The median number of URLs seen in the last five complete runs, None before the first."""
    recent = list(complete_run_counts)[-BASELINE_RUNS:]
    return int(statistics.median(recent)) if recent else None


def classify_run(outcome: RunOutcome, baseline_urls: int | None) -> RunStatus:
    if outcome.blocked:
        return RunStatus.BLOCKED
    if not outcome.enumeration_finished and outcome.urls_seen == 0:
        return RunStatus.FAILED
    if not outcome.enumeration_finished or outcome.unhandled_errors > 0:
        return RunStatus.PARTIAL
    if baseline_urls is not None and outcome.urls_seen < MIN_COMPLETENESS * baseline_urls:
        return RunStatus.PARTIAL
    return RunStatus.COMPLETE


def plan_missing(
    unseen: Sequence[UnseenListing], active_total: int, status: RunStatus
) -> MissingPlan:
    """What to do with the listings a run did not see."""
    if status is not RunStatus.COMPLETE:
        return MissingPlan((), (), False)
    due = [u.id for u in unseen if u.missed_runs + 1 >= MISSING_AFTER_RUNS]
    cap = max(MISSING_CAP_MINIMUM, math.ceil(MISSING_CAP_SHARE * active_total))
    held = len(due) > cap
    return MissingPlan(
        mark_missing=() if held else tuple(due),
        increment=tuple(u.id for u in unseen),
        held=held,
    )


def status_after_seen(current: ListingStatus, page_can_be_bought: bool | None) -> ListingStatus:
    """A listing seen again is active, or unavailable when its page says it cannot be bought."""
    return ListingStatus.UNAVAILABLE if page_can_be_bought is False else ListingStatus.ACTIVE


def gone_confirmed(gone_runs: int) -> bool:
    """A listing is discontinued only when its own URL answered 404 or 410 in two runs."""
    return gone_runs >= DISCONTINUED_AFTER_RUNS


def should_pause(consecutive_failures: int, *, blocked: bool) -> bool:
    return blocked or consecutive_failures >= PAUSE_AFTER_FAILURES
