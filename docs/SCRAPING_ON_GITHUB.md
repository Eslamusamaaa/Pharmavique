# Running the daily SFDA refresh on GitHub Actions

Status 2026-11-22: **measured, not built.** The refresh cannot run on Vercel or Neon (it needs
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

## Plan (not built yet)

A scheduled workflow, once a day, that runs the same steps as `scripts/daily_refresh.ps1`
(`sfda-update`, `sfda-load`, `sfda-withdraw-absent`, `search-reindex`, `outbox-relay`, `notify-emails`,
`analytics-rebuild`, `cache-invalidate`, then the fast lists) against Neon, using these repository
secrets: the direct Neon address, and the e-mail settings for the alerts.

What still has to be solved before it is switched on:

1. **Memory between runs.** The runner starts empty. `data/sfda/<run>` (the last complete run) is what a
   run is compared with and what `sfda-withdraw-absent` needs ("missing from two complete runs in a row").
   Keep it with `actions/cache` (or the database) and fall back to the committed baseline
   `full-20261116`.
2. **A copy of the database before each run** (a Neon branch, the Free plan allows 10), so a bad run can be
   undone. The code already refuses to load a list that has fewer than 90% of the baseline's rows and to
   withdraw more than 50 drugs at once, and a partial run never withdraws; the branch is the second net.
3. **OCR on Linux.** `sfda-list-ocr` uses `pdf_ocr_windows.py` (Windows OCR). On the runner that step has to
   be skipped (and reported in `ATTENTION.md`) or replaced.
4. **A failure must be loud.** The workflow fails (and GitHub e-mails the owner) when a step exits with an
   unexpected code; `data/refresh/ATTENTION.md` says which drugs were not checked.
5. **Pictures** (`pictures-*` steps) are not part of the first version.
6. Neon compute is awake for the whole run; two hours a day is about 15 CU-hours a month of the 100 free.

Until this is built, switch the laptop task off or point it at Neon on purpose: two refreshes that write to
different databases will drift apart.
