# Phase 0 report: trust foundation

Finished 2026-11-26. Nine items, decided with the owner on 2026-11-25 (ADR-020, ADR-021, and the
answers recorded in the hand-off). Each item was committed on its own and pushed after the five checks
passed (`ruff check`, `ruff format --check`, `mypy src tests`, `lint-imports`, `pytest`).

Checks at the end of the phase, on the developer machine with Postgres and Redis running:
ruff clean, 610 files formatted, mypy clean on 546 files, 8 of 8 import contracts kept,
**1,903 tests passed** (18 phone tests skipped without an address), and **18 of 18 phone tests passed**
against the local server, three runs in a row.

## Summary

| Item | State | What is left |
|---|---|---|
| 0.1 Sign-in and roles | done | nothing |
| 0.2 Daily refresh | done | nothing |
| 0.3 Scan accuracy | tooling done | real photos to collect and measure |
| 0.4 Look-alike names | done | nothing |
| 0.5 Phone-size tests | done | not in CI (needs the built site and browsers) |
| 0.6 Email | done | nothing |
| 0.7 Provenance and trust grades | done | nothing |
| 0.8 Deployment safety | done | the owner runs the first Neon restore drill |
| 0.9 Quality gates | done | Sentry DSN in Vercel, if not set yet |

## 0.1 Sign-in and roles

- Assistant, scan and voice need a signed-in account (behind the `login_for_ai` flag); guests see a
  Saudi-dialect "sign in" screen and come back to the same place.
- Production refuses to start without a JWT secret of 32 or more characters; development only warns.
  Production is running, so the Vercel secret passes.
- Pharmacist and company accounts sign up unverified; an operator verifies or rejects them from the
  operator screen or `verify-account`, and the person gets an email. Only the verified badge waits for it.
- Commits: e9e4436, 875cb18, d0a7600, a0a4633, 01b5075, fb2d927, 5d9703a.

## 0.2 Daily refresh

- The drugs update resumes after a lost internet connection, the cause of the earlier exit code 3.
- One JSON event per step and one per run in the refresh folder.
- Only the drugs that changed are loaded nightly, and the database is copied once a day without the
  knowledge schema, to cut Neon transfer.
- Failure alerts are GitHub's own failure emails, by the owner's choice (no new alert code).
- Commits: 9e32c91, 0396b6b, bfdc043, 66d6649.

## 0.3 Scan accuracy

- Each scanned line is marked confident or uncertain from how well its best registry name matches.
  Uncertain: the app shows the three closest names, a "none of these" search and a "retake photo"
  button, and no medical information before the person confirms.
- `scripts/scan_eval.py` reads a real-photo answer file (drug name and source link, no patient names),
  reports failure cases and prints a threshold table. Photos stay on disk, git-ignored.
- **Not done:** no real photos have been collected yet, so the 0.9 confidence threshold is a first value
  taken from typed names, not a measured one (`docs/SCAN_EVALUATION.md`).
- Commits: f2e2786, 112df00, 8e12758.

## 0.4 Look-alike names

- The owner's sentence is under the heading: "هالأسماء تشبه اسم دوائك في الكتابة أو النطق، ننبهك
  احتياطًا عشان ما يصير خلط بينهم". No review workflow (proof of concept).
- Commit: f3e81fb (the names themselves were stored earlier in `search.similar_name`).

## 0.5 Phone-size tests

- `tests/e2e/web/test_phone_screens.py`: every test runs on WebKit at an iPhone 13 size and on
  Chromium at a Pixel 5 size. They check right-to-left layout on the drawn boxes, that nothing is wider
  than the screen, the first visit, every tab, search to a drug page with its disclaimer and trust grade,
  the guest sign-in screen for assistant, scan and voice, the sources page, and that the search box does
  not make the iPhone zoom. They only read, so they may point at the live site.
- The tests found four real problems, each fixed:
  1. **The website was mirrored.** The build added `dir="rtl"` to the page, but the screens already lay
     themselves out right to left (as on a phone), so every row flipped back: the home tab, the back
     arrow, the main button and the registration number were on the left. Fixed in
     `mobile/scripts/build-web.mjs` (57b2014). The new checks fail on the old build.
  2. **The rate limit counted the website's own files.** Opening the site loads dozens of scripts, fonts
     and icons; after a few screens (or several phones behind one carrier address) a script answered
     429 and the screen broke. Website files are no longer counted; every API call still is (881efd4,
     test first).
  3. **Screen readers did not announce buttons or the open tab.** The shared button had no role, and
     react-native-web 0.21 ignores `accessibilityState`, so the selected tab and checked options were
     silent. Fixed with `aria-selected` and `aria-checked` and button roles (91ece0b).
  4. The share button on the drug page had no role (same commit).
- Not in CI: it needs the built website, a loaded database and the browsers. Run it locally, or against
  the live site after a deployment (`README.md`, section 15).
- Commits: 881efd4, 57b2014, 91ece0b, 38c1165.

## 0.6 Email

- SMTP sender with integration tests through a local Mailpit catcher
  (`docker compose --profile mail up -d mailpit`); production refuses the console sender.
- Verification and review emails are sent before the answer, so Vercel does not stop them.
- Commits: a102c73, 5d9703a.

## 0.7 Provenance and trust grades

- Three grades: official Saudi (SFDA), official foreign reference (openFDA), unverified (DDInter, MeDIC).
- A disclaimer field on every medical API answer and a small line on every medical screen; trust badges
  on interactions, contraindications and assistant citations.
- Public `GET /v1/sources` and a sources screen: source, grade, last successful update, row count,
  daily or fixed (behind the `sources_page` flag). ADR-021.
- Commits: e540563, 8725e01, be16f07.

## 0.8 Deployment safety

- `GET /ready`: 200 when the database (and the shared store, when set) answers within 5 s, else 503 with
  the failing check named and no addresses or error text. Live on production:
  `{"status":"ready","checks":{"database":"ok","shared_store":"not_configured"}}`.
- Production Docker image, a PgBouncer pooler and a compose file for a later move off Vercel
  (`docker/production/`, `docker/pgbouncer/`). Tested locally: image builds, migrations run, `/ready` 200
  through PgBouncer, a search answers, `/ready` turns 503 when PgBouncer stops. A `.dockerignore` now
  keeps `data/` and secrets out of every build.
- `docs/RUNBOOK.md`: outages, Vercel rollback, Neon restore, migrations, secrets, the move to Docker.
  `scripts/restore_drill.py` compares row counts and migration versions of two databases (read-only).
- **Left for the owner:** the first restore drill needs the Neon console (runbook section 4); the
  table there records its result. The Vercel rollback is documented, not exercised.
- Commits: 72a382d, 6bd1380, 9ed5635.

## 0.9 Quality gates

- bandit, pip-audit and gitleaks fail the CI build; unfixable findings go in an exceptions list with a
  reason.
- Locust load tests with a fake assistant model that never calls a real one; no load on production.
- Sentry reports errors and sampled latency when `PHARMAVIQUE_SENTRY_DSN` is set, with personal and
  health data scrubbed.
- Feature flags from `PHARMAVIQUE_FEATURE_*`, listed at `/v1/features`.
- Commits: 29195d4, 0e3f719, a63609c, 82bee6d, 4d0c31d, 62c8d44.

## Waiting on the owner

1. Collect real box and prescription photos for 0.3, then pick the confidence threshold from the table.
2. Run the Neon restore drill once (runbook section 4).
3. Put the Sentry DSN in Vercel if it is not there yet.
4. The grill round for Phase 1 (chat history) before it starts.
