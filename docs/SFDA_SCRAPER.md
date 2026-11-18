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

**The three giant lists** (medical equipment about 160,000 rows, food products about 1.5 million, cosmetic products about 3 million) are crawled only with `--include-giant`. At the default pace they take roughly 9 hours, 3.5 days and 7 days of list pages. They get only the two cheap targeted repair passes (not the full sweeps), so a small gap may remain; `manifest.json` reports it in `list_completeness`. Their pages are stored in sub-folders of 1,000 pages. The three giant lists use a **streaming crawler** (`list_stream.py`): each page's rows go to `records.jsonl` as soon as the page is read, only a 64-bit fingerprint per row is kept in memory (to drop repeats), and a stopped crawl continues at its last page. It makes a single pass (no repair passes), so a few rows may be missed or repeated because the list order is unstable; `manifest.json` reports `rows_read`, `unique` and `repeats`.

### Quirks found while crawling the other lists

- **What "past the end" looks like differs per list.** The drugs list repeats its last page with that
  page's number; some lists answer a page with the text "No Results Found"; others answer a page
  with the pager and no table. All three mean "the list ended"; a page with neither a table nor the
  pager is refused (it may be a block page).
- **Holes.** An empty page *inside* a list happens (page 119 of the feed list is empty, pages 118
  and 120 are full). It is skipped, recorded in the manifest (`empty_pages`) and the run is
  `partial`; five empty pages in a row stop the crawl because the site is probably failing. Empty
  pages are not stored on disk, so a later run asks for them again.
- **The cosmetic ingredients list (`AllCosmeticList`) has a pager that does not work with plain
  requests**: page 0 shows 10 rows, every other page answers "No Results Found". The list is driven
  by a filter form, which has a CAPTCHA that is never touched. Only its first 10 rows are readable;
  the rest needs an official export (OPEN_QUESTIONS Q-29).

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

### The gaps of the small lists (measured 2026-11-18)

The drugs list changes rows between fetches, but the small lists do not: for six lists, 0 of 600+ repeat fetches returned different rows for the same page, so more passes cannot find more rows. The gap (`expected` minus `unique`, where `expected` is only "full pages times 10") has two causes, told apart by where the repeated rows sit:

- **Real duplicate rows**, next to each other on one page. `drug-shortage` (3 rows) is this case: the list is complete, the "gap" is the site repeating identical rows.
- **Ties in the site's sort order**: a row seen at the end of one page again at the start of the next, so other rows are never returned. `safety-alert` (5 rows), `drug-approvals` (27) and `safety-labeling` (59) are this case. These rows cannot be reached by paging; the Arabic version of a list gives the same pages (checked for `drug-shortage`). Only the filter forms (CAPTCHA, never touched) or an official export from SFDA (OPEN_QUESTIONS Q-29) would close them.

`drug-companies` (37) is not a pure duplicate case: in the stored pages 0 repeats sit on one page, 12 sit across a page border and 24 reappear on a page further away, so it is the sort-order case and the missing rows cannot be reached by paging.

### Closing the ties with a sort (2026-11-18)

Three lists answer `?page=N&order=title&sort=asc|desc` (and safety-labeling also `order=field_trade_name`). It is a plain query on the list page, not the CAPTCHA filter form, and it gives the site a different tie-break, so rows the default order never shows appear. `ListSpec.sort_fields` names the fields; the crawler sweeps every page in each sort only while rows are missing and keeps the union. Result:

- `safety-alert`: 271 -> **276 of 276, complete**.
- `drug-approvals`: 435 -> **462 of 462, complete**.
- `safety-labeling`: stays at 241 distinct rows of 261 slots. Sorted by title, 261 rows come back with 18 repeats sitting on the same page, so the list really contains about 20 rows that are identical in every cell. Two more orderings found nothing new. Treat it as complete with identical duplicate rows.
- `drug-companies` and `drug-shortage` ignore `order`, so there is no second ordering. `drug-shortage`: 3 identical rows (complete). `drug-companies`: 37 rows stay out of reach.

### Scope decision (2026-11-18)

The owner limited the lists to what the product uses: drugs, safety-labeling, safety-alert, drug-shortage, drug-approvals, drug-companies and pharmacies. Feed, food, medical equipment, cosmetics, vet drugs and unregistered pharmaceuticals are out of scope and are not crawled further (partial data stays on disk). Their gaps are not chased.

## Result of the first full crawl (run `full-20261116`, finished 2026-11-18)

- **9,162 unique drugs**, the list complete (`list_completeness.gap = 0`; the pager alone suggested
  9,152 rows, and the first single pass had found only 8,626).
- English details for **9,145** drugs and Arabic details for **9,145** (both languages for 9,144).
  The status stayed `partial` because the details page of **18 drugs** (17 of them in English)
  answers with an empty table, even on repeated tries; SFDA itself has no details for them. Their
  list data (names, scientific name, strength, form, price) is in `records.jsonl`, so they are
  kept, without details.
- The run took about 10 hours of polite crawling, with about 110 connection resets that the
  retries and the restart script (`scripts/resume_sfda_scrape.ps1`) absorbed.
- A resume stops after 15 failing pages in a row, so with the 18 empty pages in the list it will not
  finish by itself; that is expected.

## Loading the lists into the catalog and linking them to drugs (2026-11-18)

`pharmavique sfda-lists-load` replaces each of the six product lists (safety-labeling, safety-alert, drug-shortage, drug-approvals, drug-companies, pharmacies) in `catalog.source_list_rows` and writes `catalog.source_list_links` (migration `catalog_0002`, reversible). Rows keep their provenance and trust. A link is `matched` (evidence agrees) or `possible` (needs a person or a pharmacist), never a claim of identity on thin evidence:

- safety-labeling, drug-approvals: same brand and same set of substances is `matched`; same brand with a different substance set is `possible`; an unknown brand never links, even if the substance is known;
- drug-shortage (generic name only) and safety-alert (a title that names an ingredient): always `possible`;
- drug-companies: `matched` when the company name (country suffix dropped) equals a manufacturer, marketing company or agent of a product;
- pharmacies: no drug link (they feed the nearby-pharmacy map).

First load (lists-1): safety-labeling 241 rows, 113 linked; safety-alert 276, 221 linked (4,448 possible links, noisy by design); drug-shortage 723, 708 linked; drug-approvals 462, 448 linked; drug-companies 6,135, 2,045 linked; pharmacies 385, none. Strength is not compared yet, so a link means "this brand or substance", not "this exact pack".
