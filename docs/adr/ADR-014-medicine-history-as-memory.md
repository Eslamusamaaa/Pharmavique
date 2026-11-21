# ADR-014: the patient's medicine history as memory

Status: accepted, 2026-11-21 (owner: keep each patient's medicines as a history, and when they ask
about a new drug, check it against what they already take and warn about recorded conflicts).

## Context

A signed-in patient already saves medicines on the server (`watchlist`, under row-level security) and
records allergies. The interaction data (`interactions`, DDInter and openFDA) can say which pairs of
ingredients have a recorded interaction. Nothing joined them for a new drug the person asks about.

## Decision

- **The saved list is the history.** Each saved medicine now has a `status` the person sets themselves:
  `current` (taken now) or `past` (taken before). Both are kept with their dates; deleting stays
  possible. Only `current` medicines are compared with a new drug and only they raise alerts.
  "Past" is the person's own record, never our advice to stop anything.
- **`GET /v1/me/history/check/{register_number}`** compares a drug's active ingredients with the
  person's current medicines through the existing `interactions` contract and returns only findings
  that involve the new drug (an interaction between two of the person's other medicines is not about
  this drug), plus a duplicate ingredient finding when two medicines share one, the person's allergy
  matches by name, and the ingredients the source cannot judge. `GET /v1/me/history/interactions`
  lists recorded interactions among the current medicines.
- **A finding is a source's statement**: the severity as the source rates it (`ddinter-2.0`, openFDA),
  never our own. `complete` is always false and every answer says that no finding is not "safe". No
  dosing, no "stop", no "switch": the notes say not to change a medicine or a dose because of the
  screen.
- **The assistant can attach the same check** when the signed-in person asks for it
  (`use_history: true` with a drug). The comparison runs on the server from recorded interactions and
  is attached to the answer; **the language model never receives the person's medicines**, so no
  health history goes to an outside provider. Without a sign-in this is a 401, without a named drug a
  422, and a bad token is never treated as anonymous. Background jobs do not support it yet (422).
- The comparison is composed in the composition root (`bootstrap/history.py`) from the watchlist, the
  catalog and the interactions contracts; none of the three imports another.
- Checked on the real data (2026-11-21): taking COUFATEX (warfarin) and asking about ASPICARD
  (aspirin) gives a `major` interaction from `ddinter-2.0`; marking the warfarin as past removes it.

## Consequences

- The check is only as good as the sources: they are incomplete, match by ingredient name (a name the
  source does not know is returned as "cannot judge"), and cover interactions, not doses, timing, food
  or the person's conditions.
- The person's list is health data, opt-in and behind row-level security, and is deleted with the
  account. Real users need the legal review the owner will schedule when this leaves the prototype
  stage.
- Not built: the person's conditions (contraindications need them), reminders, a timeline view of
  when each medicine started and stopped, and using the history inside the language model's answer
  (deliberately not done).
