# Running the daily SFDA refresh on GitHub Actions

Status 2026-11-22: **built** (`.github/workflows/daily-refresh.yml`, `scripts/daily_refresh.sh`); it runs once the repository secrets below are set. The refresh cannot run on Vercel or Neon (it needs
Chromium and about two hours; a Vercel function stops after 300 s and Vercel Cron on the Hobby plan
runs once a day at most). Today it runs only as the Windows task `PharmaviqueDailyRefresh` on the
owner's laptop and writes to the **local** database, so the Neon database is not refreshed.

## What was measured

- From a GitHub-hosted runner (Ubuntu, United States, Microsoft Azure) the SFDA site answered
  `robots.txt` and `/en/drugs-list` with HTTP 200 (4 to 6 s per request).
- Our own crawler (`pharmavique sfda-update --baseline full-20261116`) ran there for 4 minutes and read
  list pages 0 to 120 of 459 without a block, about 1.8 s a page. The whole list is about 14 minutes.
  Workflow: `.github/workflows/sfda-probe.yml` (manual, writes nothing anywhere).
- The laptop's own history: 2026-11-21 the drug update stopped after 21 minutes (exit 3, `aborted`);
  2026-11-22 it finished `partial` after 80 minutes and the lists crawl took 50 minutes (exit 2).
  So a full daily refresh is about two hours and the laptop's connection makes it unreliable.
- The repository is public, so GitHub-hosted minutes are free. A job may run 6 hours.

## How it runs

`.github/workflows/daily-refresh.yml` runs every day at 01:17 UTC (04:17 in Saudi Arabia; off the hour, when GitHub delays or drops fewer scheduled runs) and by hand
(Actions, Daily refresh, Run workflow; a short trial: steps `lists`, lists `drug-shortage`). It calls
`scripts/daily_refresh.sh`, the Linux twin of `scripts/daily_refresh.ps1`:

1. `sfda-update` against the last complete run (or the committed baseline `full-20261116`), then
   `sfda-load`, `sfda-withdraw-absent`, `search-reindex`, `outbox-relay`, `notify-emails`,
   `analytics-rebuild` and `cache-invalidate`.
2. The fast lists (`sfda-lists`), loaded only when a list has at least 85% of the baseline's rows; the new
   rows of the knowledge lists get their documents read and their chunks added and embedded.

**Safeguards.** Two runs never overlap (`concurrency`). Before every run the four registry schemas are
copied with `pg_dump` and kept two days as an artifact (`database-before-refresh`); they hold public
registry data only, never accounts. The code refuses a list under 85% of the baseline, never withdraws more
than 50 drugs at once, and never withdraws after a partial run. A step that fails does not stop the next
one, but the job ends red and GitHub e-mails the owner; `ATTENTION.md` and the job summary say what was not
checked. The state of the last runs (`data/sfda`, `data/lists`) is kept with `actions/cache`.

**Restoring.** Download the artifact, then load it with `pg_restore --data-only --single-transaction` after
emptying the tables (the same way `scripts/db_copy_remote.sh` loads), or ask for a branch restore in Neon.

**Repository secrets** (Settings, Secrets and variables, Actions): `NEON_DIRECT_URL` (the direct, not the
pooled, address), `PHARMAVIQUE_JWT_SECRET` (the same value as on Vercel: it signs the unsubscribe links),
`PHARMAVIQUE_OPENROUTER_API_KEY`, `PHARMAVIQUE_CLOUDFLARE_API_TOKEN`, `PHARMAVIQUE_CLOUDFLARE_ACCOUNT_ID`
(embeddings), and the e-mail settings `PHARMAVIQUE_EMAIL_BACKEND`, `PHARMAVIQUE_EMAIL_FROM`,
`PHARMAVIQUE_SMTP_HOST`, `PHARMAVIQUE_SMTP_PORT`, `PHARMAVIQUE_SMTP_USERNAME`, `PHARMAVIQUE_SMTP_PASSWORD`.

## Not covered

- **OCR of scanned PDFs** (`sfda-list-ocr`) uses the Windows OCR: scanned documents are added without text and
  the step is marked skipped in the summary.
- **Pictures** of new drugs are not refreshed by this workflow.
- Neon compute is awake for the whole run: about two hours a day is about 15 of the 100 free CU-hours a month.
- The Windows task `PharmaviqueDailyRefresh` writes to the local database; once this workflow has run
  correctly it is switched off so the two never drift apart.
