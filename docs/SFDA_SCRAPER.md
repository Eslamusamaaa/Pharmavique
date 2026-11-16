# SFDA scraper: how to run it

Code: `src/pharmavique/ingestion/infrastructure/connectors/sfda_web/`. Data source and legal status: [DATA_SOURCES.md](DATA_SOURCES.md).

## One-time setup

```bash
uv sync
uv run playwright install chromium   # downloads the browser once (about 125 MB)
```

## 1. First time: full crawl

```bash
uv run pharmavique sfda-scrape --run-id full-20261116
```

- About 460 list pages plus two details pages (English and Arabic) per drug: roughly 19,000 requests at 1.5 s plus jitter, so **about 10 to 12 hours**.
- Safe to stop (Ctrl-C) or to lose power: run the same command again with the same `--run-id` and it continues from the stored pages, fetching only what is missing.
- Output in `data/sfda/<run-id>/`:

| File | Meaning |
|---|---|
| `manifest.json` | status (`complete`, `partial`, `blocked`, `aborted`, `interrupted`), counts, failures, provenance, config |
| `records.jsonl` | one drug per line: list fields, English fields, Arabic fields, provenance per language |
| `list/`, `details/en/`, `details/ar/` | the stored pages (gzip), so parsing can be redone without refetching |
| `crawl.log` | progress log |

- When the status is `complete`, `data/sfda/latest.json` points at that run. It is the baseline for updates.
- Useful options: `--max-pages 2 --max-details 10` (small sample, status `partial`), `--delay 2.5` (slower), `--headed` (show the browser).

## 2. Every time after that: update only what changed

```bash
uv run pharmavique sfda-update
```

What it does:

1. Reads **every list page** (about 460 requests, roughly 15 to 20 minutes) and compares them with the baseline.
2. Fetches the English and Arabic details **only for drugs that are new or whose list fields changed** (name, strength, form, price).
3. Also re-fetches the details of the `--recheck N` drugs whose details are oldest (default 300). This is how changes that are not visible on the list, such as authorization status, are found. With about 9,200 drugs and 300 per run, every drug's details are re-checked about once a month.
4. Everything else is carried over unchanged from the baseline, with its original fetch time.
5. Writes `changes.json` and `changes.md` in the new run folder (added, removed from the list, price changes, other field changes), prints a one-line summary, and moves `latest.json` forward if the run completed.

Limits to know:

- A change that is **only** in the details pages is found when that drug comes up in the re-check, so it can take up to a month with the default. Raise `--recheck` for faster detection (more requests per run).
- A drug that disappears from the list is reported as "removed from the list". The list alone does not say whether it was withdrawn or just unlisted.
- If a changed drug's details cannot be fetched, the new list fields are kept, the old details are kept, and the failure is recorded in `manifest.json` (status `partial`, baseline not moved).

Compare any two runs offline: `uv run pharmavique sfda-diff <old-run> <new-run>`.

## 3. Running it on a schedule

Windows (daily at 03:00; the computer must be on, a missed run starts when it is next available):

```powershell
.\scripts\schedule_sfda_update.ps1 -Time 03:00
.\scripts\schedule_sfda_update.ps1 -Remove     # to undo
```

Linux or a container (cron): `0 3 * * * /path/to/repo/scripts/run_sfda_update.sh 300`.

Each scheduled run appends to `data/sfda/update.log`. Do not start the schedule before the first full crawl has finished; without a baseline `sfda-update` exits with code 4.

Later, once the worker from ADR-002 exists, the same command becomes a scheduled job there.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | complete |
| 2 | partial (some pages failed or a sample was requested) |
| 3 | stopped: blocked by the site (401/403/429), disallowed by robots.txt, too many failures |
| 4 | no baseline to update from |

If a run stops with code 3, **do not work around it**. Wait, check the site in a browser, and consider contacting SFDA.
