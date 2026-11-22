"""When a drug that is no longer on the SFDA list may be withdrawn from the catalog.

The list alone does not say a drug was withdrawn, and the site's list is unstable: one pass over
it misses about one drug in sixteen. So a drug is withdrawn only when all of these hold:

- the run that did not see it was complete (no gap, no failed page);
- the run before it (the baseline the update compared with) did not see it either, so it was
  missing twice in a row;
- no more than `max_withdrawals` drugs qualify at once, otherwise something is wrong with the
  source and nothing is withdrawn.

Pure function, no I/O and no framework.
"""

from collections.abc import Collection
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WithdrawalPlan:
    to_withdraw: tuple[str, ...]  # register numbers to withdraw now
    pending: tuple[str, ...]  # missing in this run only: withdrawn if the next run misses them too
    blocked_reason: str | None  # why nothing is withdrawn, when that is the case


def plan_withdrawals(
    *,
    listed: Collection[str],
    seen_now: Collection[str],
    seen_before: Collection[str],
    run_is_clean: bool,
    max_withdrawals: int,
) -> WithdrawalPlan:
    """`listed`: register numbers the catalog holds as listed. `seen_now` and `seen_before`: the
    keys the latest run and the run before it found on the list."""
    now = set(seen_now)
    before = set(seen_before)
    missing = sorted(key for key in set(listed) if key not in now)
    confirmed = tuple(key for key in missing if key not in before)
    pending = tuple(key for key in missing if key in before)

    if not run_is_clean:
        return WithdrawalPlan(
            (), pending, "the run was not complete, so a missing drug proves nothing"
        )
    if len(confirmed) > max_withdrawals:
        return WithdrawalPlan(
            (),
            pending,
            f"{len(confirmed)} drugs qualify but the limit is {max_withdrawals}: "
            "nothing was withdrawn, check the source before raising the limit",
        )
    return WithdrawalPlan(confirmed, pending, None)
