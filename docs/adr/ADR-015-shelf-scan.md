# ADR-015: the pharmacist's shelf scan

Status: accepted, 2026-11-21, **shipped behind a flag, off by default** (owner asked for it; Q-12
answered: use the vision model already configured for the box scan; Q-32 still open: no real shelf
photos exist yet).

## Context

The box scan reads one box and the prescription scan reads a list. A pharmacist also wants to point the
phone at a shelf and get the medicines on it. Reading many boxes in one photo is harder than reading
one, and nobody has measured how well the configured vision models do it on real shelves: there are
no shelf photos to measure with.

## Decision

- **A third scan kind, `shelf`, on the same endpoint** (`POST /v1/recognition/scan?kind=shelf`, and the
  background job endpoint): the same vision readers, a different prompt ("list every box whose name you
  can read; do not count units, do not identify a box by colour or shape, do not read prices"), the
  same candidate matching against the registry, up to 40 lines, and one line per distinct name and
  strength (the same box seen twice is one line). Every line needs review, its match score is always
  shown, and no dose is ever read.
- **Off by default** (`PHARMAVIQUE_SHELF_SCAN_ENABLED`, `GET /v1/features` tells the app). When off the
  endpoint answers 404 for `kind=shelf`; the box and prescription scans are unaffected. The owner
  switches it on to try it on real photos.
- **Pharmacists only**: a signed-in pharmacist (or the operator) is needed, otherwise 401 or 403.
- **Nothing is added automatically.** The app shows each proposed box with up to three registry
  candidates and their scores; the pharmacist ticks the right one and confirms. Only confirmed medicines
  join the **shelf list** (`POST /v1/me/shelf`, at most 100 at a time, unknown register numbers are
  refused and reported).
- **The shelf list** (`watchlist.shelf_items`, migration `watchlist_0003`) is per pharmacist, under the
  same forced row-level security as the other personal tables, deleted with the account, at most 2,000
  medicines. It says which medicines the pharmacist shelves; **it holds no counts and says nothing
  about stock.** A medicine on the shelf list raises the same alerts as a saved one (a price change,
  a withdrawal), because the alert handler's holder lookup includes it.
- The photo is read in memory and dropped; nothing about a shelf is stored but the confirmed list.

## Consequences

- Until real photos exist the accuracy is unknown. The first thing to do when the flag is turned on is
  to run a set of real shelf photos, label them, and measure how many boxes are read, how many are
  matched to the right register number and how many are missed (Q-32); thresholds and the 40-line cap
  are guesses until then.
- Names that look alike (LASA) matter more on a shelf than anywhere: the screen shows the score, but
  the scan does not yet lower its confidence for confusable names.
- Not built: counts, expiry dates, a per-pharmacy tenant list shared by several pharmacists (the list
  is per account), and a shelf photo history.
