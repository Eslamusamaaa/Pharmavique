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

## 4. The other official lists (shortages, pharmacies, companies, ...)

`sfda-lists` crawls the 13 other official SFDA lists (catalog in `docs/DATA_SOURCES.md`, SA-3) one after another, with the same rules as the drugs crawl: public pages only, robots.txt first, stop on 401/403/429, nothing stored unless it parses, repeat fetches to cope with the unstable order. It reads **list pages only** (no details pages yet); column names are taken from each page, never guessed.

```bash
uv run pharmavique sfda-lists --show                    # the known lists and their size
uv run pharmavique sfda-lists                           # every list except the three giants
uv run pharmavique sfda-lists --lists drug-shortage,pharmacies
uv run pharmavique sfda-lists --include-giant           # also the three giants, see below
uv run pharmavique sfda-lists --run-id lists-1          # run again with the same id to resume
```

Output: `data/lists/<list>/<run-id>/` with `manifest.json`, `records.jsonl` (one row per list row, with provenance) and the stored pages. A list that is already `complete` in the run is skipped, so the whole queue can be restarted safely. If the site blocks the crawl, the whole queue stops; any other failure marks that list `aborted` and the queue moves on (exit code 2).

**The three giant lists** (medical equipment about 160,000 rows, food products about 1.5 million, cosmetic products about 3 million) are crawled only with `--include-giant`. At the default pace they take roughly 9 hours, 3.5 days and 7 days of list pages. They get only the two cheap targeted repair passes (not the full sweeps), so a small gap may remain; `manifest.json` reports it in `list_completeness`. Their pages are stored in sub-folders of 1,000 pages. Known limit: the crawler keeps the rows of a list in memory while it works, which is fine up to a few hundred thousand rows but not for the 1.5 and 3 million row lists; a streaming mode is still to be built before those two are started.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | complete |
| 2 | partial (some pages failed or a sample was requested) |
| 3 | stopped: blocked by the site (401/403/429), disallowed by robots.txt, too many failures |
| 4 | no baseline to update from |

If a run stops with code 3, **do not work around it**. Wait, check the site in a browser, and consider contacting SFDA.

## Known quirk: the list order is unstable

Found 2026-11-17. If you fetch the same list page twice, the site often returns different rows near the edges of the page (about half of the repeat fetches differed). One drug can appear on two pages while another appears on none, so a single pass over the 458 pages misses drugs: the first pass found 8,626 of an expected 9,152 rows, and three targeted repair passes reached 9,026.

What the crawler does about it:

- Fetching a page again is allowed and cheap, and the union of everything seen is kept (stored under `list/pass-02`, `pass-03`, and so on).
- Passes 2 and 3 refetch the pages that look wrong (a page equal to the one before it, or sharing drugs with another page). Later passes sweep **every** page, because a skipped drug leaves no duplicate to point at.
- It stops when nothing is missing, after 3 passes in a row that find nothing new, or after 8 passes (`max_list_passes`, `list_patience`).
- `manifest.json` reports `list_completeness` (`expected`, `unique`, `gap`, `passes`). A run with a gap above zero is `partial`.

The end of the list is read from the pager: past the last page the site returns the last page again, labelled with its real number, so a label lower than the requested page means the list ended.

To close the remaining gap after a run: resume it with the same `--run-id`. The stored pages are reused and only the extra passes and the details of newly found drugs are fetched.
