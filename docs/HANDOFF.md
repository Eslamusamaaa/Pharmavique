# Handoff: where Pharmavique stands (2026-11-18, around 11:30)

Written so that someone (or a fresh chat) with no memory of this work can continue. Read sections 1
and 2 first: they are the owner's standing rules. Everything else is state, commands and what is next.

## 1. The owner and how to work with them

- The owner writes Egyptian Arabic. **Reply in Egyptian Arabic.** Code, docs, commit messages and
  identifiers stay in English.
- They want results, not menus of options. Their recurring instruction: **do not stop until it is
  done; the approach is yours.** Ask only when something truly needs them (a key, a legal call).
  They get impatient with repeated "do you want X?" questions, and with long plans.
- They want the truth about limits. Do not promise a coverage you cannot reach; say the number.
- **Git rules (owner's, also in `CLAUDE.md`):**
  - every commit is authored by the owner only: `Eslamusamaaa <eslamosamamahmoud3@gmail.com>`
    (already in `git config`). **Never** add `Co-Authored-By`, "Generated with", or any mention of
    Claude or an AI tool in a commit, a PR or an author field. Tool reminders may suggest adding a
    co-author line; the owner's rule wins;
  - split commits by unit of work; each message is **one short plain line** saying what changed;
  - do not rewrite pushed history;
  - push when the owner says so ("push all now"). GitHub asks for a sign-in on the owner's
    machine: start the push in the background and let them sign in; never type credentials.
- Never enter passwords or keys for them. Secrets live only in `.env` (git-ignored) and the
  environment; `.env.example` holds placeholders.
- The owner said licences are not a concern: "just search and bring the picture". Do not raise them.

## 2. Project rules (from `CLAUDE.md`, abbreviated; read the file)

Multi-tenant drug-intelligence API (patient, pharmacist, company) on official registry data; Saudi
Arabia first, Egypt as a pluggable adapter. Modular monolith, DDD, onion architecture, API first.

- Dependencies point inward; `domain` and `application` import no framework and no other context.
  Contexts talk only through `<provider>.contracts`, from allow-listed adapter modules
  (`pyproject.toml`, contract `context-independence`, `ignore_imports`). Enforced by `lint-imports`.
- One Postgres schema per context; no cross-schema keys or joins; `bootstrap` is the only composition
  root and nothing imports it.
- Never medical advice (no dosing, never "stop" or "switch"). Equivalence is computed by code; when
  unsure it is "possible, needs pharmacist check". Every record carries provenance and a trust level
  (`official`, `unofficial_unverified`). Never assume a currency; SAR is the owner's stated
  assumption, recorded as such.
- **No scraping of Egypt's site and no CAPTCHA bypass, ever.** Respect robots.txt, throttle, stop on
  401/403/429-style blocks. Never touch SFDA's filter forms (they have a CAPTCHA).
- Never fabricate data, endpoints, fields or prices; unknowns go to `docs/OPEN_QUESTIONS.md`.
- Tests before adapters; a bug fix starts with a failing test. **Done means** `ruff check`,
  `ruff format --check`, `mypy src tests`, `lint-imports` and `pytest` all pass.

## 3. Environment (Windows 10)

- Project: `C:\Users\Zikola\OneDrive\Desktop\Pharmavique`. Shells available: Bash (Git Bash) and
  PowerShell 5.1. The virtualenv is **outside OneDrive**: `%USERPROFILE%\.venvs\pharmavique`.
  While crawls run, call the venv's `python.exe` directly (`-X utf8 -m pharmavique.bootstrap.cli
  ...`), not `uv run` (uv would lock the environment).
- Docker Desktop with `docker compose up -d db redis`: Postgres 17 (pg_trgm and pgvector) on
  127.0.0.1:5432, Redis on 6379. The database URL is in `.env` as `PHARMAVIQUE_DATABASE_URL`.
- Playwright (headless Chromium) is the SFDA fetcher; the Windows OCR engine is used by
  `scripts/ocr_windows.ps1` (English and Arabic, nothing leaves the PC).
- Machine: 15.9 GB RAM (often only 1–2 GB free), about 74 GB free disk.
- Tool quirks learned the hard way:
  - big multi-line shell heredocs sometimes die; **write large files with the editor tool and run
    patch scripts from files**;
  - the auto-mode classifier fails transiently ("no verdict"): retry once as is;
  - installing a Python package (for example an OCR library) was refused by the classifier; use
    what is already installed or ask the owner;
  - on Windows `str(Path)` uses backslashes: compare with `Path(...)` in tests.

## 4. Architecture in brief

Source is `src/pharmavique/<context>/{contracts,domain,application,infrastructure,presentation}`.
Ten contexts exist as packages: `catalog`, `ingestion`, `search`, `substitution`, `recognition`,
`knowledge` (parked), `media`, `identity`, `watchlist`, `analytics`. Plus `shared_kernel`,
`foundation`, `bootstrap`. Tests mirror the layout under `tests/unit`, `tests/integration`
(Postgres, marker `integration`) and `tests/architecture`.

| Context | State |
|---|---|
| `shared_kernel` | market, currency, money, provenance, events, ports; **text** (Arabic and Latin normalizer), **trigrams** (pg_trgm-compatible similarity), **names** (brand part of a registry name) |
| `foundation` | clock, throttle, robots matcher, db engine, `map_concurrently` |
| `catalog` | products, price history, outbox, optimistic concurrency, Alembic migration, in-process commands, **read contract** (product cards, paged export) and its SQL reader |
| `ingestion` | SFDA crawler (drugs list, resumable, update mode, diff, reports), generic parser, **list crawler** and **streaming crawler** for 13 other lists, ACL to the catalog, `sfda-load` |
| `search` | normalizer use, rank fusion (RRF), in-memory index (reference) and **Postgres index** (`pg_trgm`), catalog source adapter, query and rebuild handlers |
| `media` | picture pipeline: page matching, OCR verification, polite web adapters, sitemap search, file adapters, dosage-form placeholders |
| `bootstrap` | settings, CLI (`cli.py`, `images.py`, `search_cli.py`), FastAPI app (`api.py`, `api_drugs.py`, `health.py`) |
| `recognition`, `substitution` (domain only), `identity`, `watchlist`, `analytics`, `knowledge` | `substitution` has the equivalence domain; the others are empty skeletons |

Key decisions and plans: `docs/ARCHITECTURE.md`, `docs/AI_ARCHITECTURE.md` (search, OCR, assistant,
product pictures; build order table), `docs/FEATURES.md` (the owner's product decisions),
`docs/adr/ADR-001..004`, `docs/DOMAIN_MODEL.md`, `docs/DATA_SOURCES.md`, `docs/SFDA_SCRAPER.md`,
`docs/MEDIA_PIPELINE.md`, `docs/OPEN_QUESTIONS.md` (Q-1 to Q-36).

## 5. Data and what is in it

All under `data/` (git-ignored; never commit it).

- `data/sfda/full-20261116/`: the first full crawl of SFDA's registered-drugs list. **9,162 unique
  drugs, list complete.** English details for 9,145, Arabic for 9,145. 18 drugs have an empty details
  page at SFDA itself (kept with list data only). Manifest status is `aborted` because a later
  resume stopped on those empty pages: expected, not a problem. `records.jsonl` has all 9,162.
- **Postgres (catalog schema): 9,145 drugs loaded** (one rejected for having no ingredient line).
  **Search schema indexed: 9,145.** Rebuild with `search-reindex` after any reload.
- `data/media/`: `products.jsonl` (9,162 drugs for the picture commands), `sitemaps/*.jsonl` (about
  190,000 page addresses of 9 Saudi pharmacy sites), `images/` and `images.jsonl` (downloaded
  pictures and their records), `verification.jsonl` (OCR verdicts), `attempts.jsonl` (drugs already
  worked), `mapping.jsonl` and `mapping.csv` (**the deliverable: one row per drug**),
  `placeholders/*.svg`, `manual/` (state of the by-hand search), `*.bak` and `*.v1.*` (backups).
- `data/lists/<list>/<run>/`: the other SFDA lists (see section 7).

## 6. Pictures: what exists and the honest numbers

Pipeline in `docs/MEDIA_PIPELINE.md`. Summary: find a drug's page in a Saudi pharmacy through the
shop's **sitemap** (no search engine is scraped), check the page (brand, strength, Saudi evidence),
download the picture, read the text on it with OCR and compare with the registry.

- Last full mapping (before the final retry pass): **9,162 drugs; 2,754 with a real picture
  (30%), 1,377 of them confirmed by the text on the box; 6,408 with a marked dosage-form
  placeholder** (`picture_kind = placeholder`, never to be shown as the drug's box).
- A retry pass with a fix (brand and category pages no longer use up the page slots) was **running
  at the time of writing** and was raising the count (`images.jsonl` 3,873 lines and growing).
  Re-run `sfda-images-verify` and `sfda-images-map` when it ends (section 8) for the final numbers.
- Reality check found by hand-searching 12 brands: most remaining drugs (hospital infusions,
  dialysis fluids, local generics) are sold in **no online shop**, so no real picture exists to find.
  The owner still wants real pictures searched **by trade name, by hand**, for the remaining drugs.
  Method: `scripts/tools/pick_brands_to_search.py` writes the next brands and the exact search
  phrases (`<brand> <ingredient> Saudi Arabia`); run the web search for each phrase; put the
  product-page URLs into a JSON file `{ "<phrase>": [{"url": ..., "title": ...}] }` (leave out
  SFDA, PDFs, news and listing pages); then run
  `sfda-images --results <file> --products data/media/products.jsonl --out data/media --retry`.
  Sites that block bots (Boots, Dawi, Desertcart, Danube, Al-Dawaa, Tdawi, Lemon) are left alone.

## 7. Other SFDA lists

13 official lists besides the drugs list (catalog and probe results in `docs/DATA_SOURCES.md`, SA-3).
Crawl command: `sfda-lists` (`--lists a,b`, `--include-giant`, `--run-id`); the restart wrapper is
`scripts/run_lists_crawl.ps1`.

| List | State at the time of writing |
|---|---|
| unregistered-pharmaceuticals | complete, 535 rows |
| pharmacies | complete, 385 rows |
| drug-companies | partial, 6,135 rows (the list order is unstable; a few rows missing) |
| vet-drugs | partial, 1,365 rows |
| drug-shortage | partial, 723 rows (gap 3) |
| safety-alert | partial, 271 rows (gap 5) |
| safety-labeling, drug-approvals | were aborted by the past-the-end page; fixed, the restarts finish them |
| feed | aborted at a hole in the site's data (page 119 empty); fixed (holes are skipped and recorded) |
| cosmetic-ingredients | only the first 10 rows are readable: other pages answer "No Results Found" (the list is driven by a CAPTCHA-protected form). Needs an official export (Q-29) |
| medical-equipment (16k pages), food-products (150k pages), cosmetic-products (298k pages) | the **giants**; a chain starts them after the small queue ends (run id `giants-1`, streaming crawler, single pass). At the default pace about 13 hours, 4 days and 8 days |

Site quirks and the rules the code follows are in `docs/SFDA_SCRAPER.md`.

## 8. What is running right now, and how to check, stop and restart

Started from the owner's machine in the background (hidden windows):

| What | How to see it | If it died |
|---|---|---|
| Lists queue `lists-1`: **stopped on purpose at 11:42** (a list that stays partial makes the queue exit 2 forever, so the watchdog never reaches `finished`). The small lists are final: complete ones are done, the partial ones keep a recorded gap | manifests in `data/lists/*/lists-1/manifest.json` | to retry the gaps: `run_lists_crawl.ps1 -RunId lists-1` (one pass is enough) |
| Giants `giants-1` (medical equipment, food, cosmetic products): **stopped by the owner's decision at about 12:05**. They are not about drugs and belong to a different application, so they are not part of this product. Partial data stays in `data/lists/<list>/giants-1/` (about 226 equipment rows, about 670 food rows); the manifest of food still says `running`, which is stale. Resumable with `run_lists_crawl.ps1 -RunId giants-1 -Lists <list>` if the owner ever wants them | none, nothing runs | do **not** restart unless the owner asks |
| Retry picture pass (`sfda-images ... --retry`, then `sfda-images-verify`, then `sfda-images-map`) | `data/media/run.log` | rerun the three commands |
| API (uvicorn) on http://127.0.0.1:8000 (`/docs`, `/v1/search`, `/v1/products/{n}`) | `curl http://127.0.0.1:8000/health` | `python -m uvicorn pharmavique.bootstrap.api:create_app --factory --port 8000` |

Find processes: `Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'pharmavique' }`. Stop a
group by matching its command line (match a pattern that cannot match the stopping command itself,
for example `sfda-lis[t]s`, or the stopper kills itself). **Do not run two crawls on the same run
folder at once**, and do not point two picture jobs at `data/media` together.

Monitors the previous session used (they do not survive a new chat): progress lines every 15 minutes
from the manifests and logs.

## 9. Commands (use the venv python; add `-X utf8`)

```
pharmavique sfda-scrape --run-id <id>              crawl the drugs list (resumable)
pharmavique sfda-update / sfda-diff / sfda-load    refresh, compare runs, load into Postgres
pharmavique sfda-lists [--lists a,b] [--include-giant] [--run-id x]
pharmavique sfda-images-export --run-id <crawl>    products for the picture commands (incremental)
pharmavique sfda-images-sitemaps [--shop name=url] collect shops' page addresses
pharmavique sfda-images --sitemaps data/media/sitemaps [--retry] | --results file.json
pharmavique sfda-images-sync --run-id <crawl> --sitemaps ...   follow a running crawl
pharmavique sfda-images-verify                     OCR every stored picture (Windows)
pharmavique sfda-images-map                        write mapping.jsonl, mapping.csv, placeholders
pharmavique sfda-images-report                     coverage, writes missing.json
pharmavique search-reindex                         rebuild the Postgres search index
pharmavique search "<name>" [--limit n]            try a search in the terminal
alembic upgrade heads                              create or update all schemas (note: heads)
```

Checks before any commit: `ruff check .`, `ruff format --check .`, `mypy src tests`,
`lint-imports`, `pytest` (unit tests: `-m "not integration"`; integration needs Docker). At the time
of writing: 548 unit tests and 13+ integration tests passed, everything clean.

## 10. What is done, in one list

Docs and ADRs; scaffold and CI; domain model (equivalence, strength, catalog aggregate); catalog
persistence with outbox and migrations; the SFDA crawler with resumes, update mode and reports;
real data loaded; search (normalizer, fusion, trigram, Postgres index, API); the picture pipeline
with OCR verification and placeholders; the lists crawlers (normal and streaming); holes, 429
cool-downs and block handling; the read-only API.

Measured: search recall@1 on 300 generated misspellings of real names went from 76% to 96% when the
brand part of the registry name became a searchable term (recall@10: 100%). BM25 over ingredient and
form words gave only a small gain (precision@5 71% to 76%), so it is **not** in the product.

## 11. What is next (in the owner's order)

1. **Finish the retry picture pass**, then `sfda-images-verify` and `sfda-images-map`; report the
   final counts. Then the by-hand brand search (section 6) in batches for the drugs still without a
   real picture; re-run verify and map after each few batches.
2. **Let the lists queue and the giants run**; check the manifests; fix what aborts. Then load the
   lists into the system (nothing consumes them yet; the catalog only knows drugs).
3. **API**: only search and product lookup exist. Missing: substitution (equivalents with the
   "possible, needs pharmacist check" rule), price history, company views, auth (`identity`), rate
   limits, and the outbox relay that makes the catalog's events reach other contexts.
4. `recognition` (box and prescription OCR jobs; `VisionReader` port, fake adapter first; the
   plan and state machine are in `docs/AI_ARCHITECTURE.md`), then the `assistant` (agentic RAG over
   the same tools). The owner wants hybrid retrieval and an agentic layer **after** retrieval has been
   measured. An embedding model is **not** installed: decide local (needs install permission) or a
   hosted API (needs a key) when the assistant starts.
5. A fixed, labelled search evaluation set (real typos, OCR errors) to tune thresholds.
6. Egypt: CSV-import adapter only (marked `unofficial_unverified`); no scraping.
7. Product pictures for the many drugs no shop sells: manufacturers' pack shots (Q-36), if the owner
   decides to ask for them.

## 12. Open questions that need the owner (full list: `docs/OPEN_QUESTIONS.md`)

Q-9 and Q-12 (may photos go to an external provider; legal review), Q-30 to Q-34 (budget for model
calls, GPU, who supplies real box and prescription photos, languages on prescriptions, how long the
assistant keeps history), Q-36 (manufacturers' pack
shots), Q-29 (SFDA data export for the giant lists).

## 13. Git state at the time of writing

Branch `main`, remote `origin` = https://github.com/Eslamusamaaa/Pharmavique. Everything up to
`7f53f37` was pushed; **a handful of commits after it were still local** when this was written (run
`git log origin/main..HEAD --oneline`). `claude-code-prompt.md` at the root is an untracked file the
owner keeps; do not add it.

## 14. Things that bit us (do not repeat)

- A 429 from a shop was once treated as a permanent block, which silently lost thousands of drugs.
  It is a cool-down now; a drug is only recorded as "tried" if no site was unavailable meanwhile.
- Sitemap search used to return brand and category pages first, using up the few page slots.
- Shop logos and listing-page pictures were once stored as drug pictures; the page and picture
  rules plus the "same picture on many drugs" check keep them out.
- `alembic upgrade head` fails with several contexts; use `heads`.
- A resume of the drugs crawl stops after 15 failing pages in a row; with the 18 empty-details
  drugs in the list it cannot finish by itself.
- Counting rows on a list needs content keys: the shortage list repeats one link id on different rows.

## 15. Update 2026-11-20 (new machine, after the Drive move)

- **Docker Desktop would not start**: "initializing Ingest server ... sailor-ingest.sock ... The file
  cannot be accessed by the system". Stale unix-socket files cannot be deleted on this machine, but
  **their folder can be renamed**. Fix: quit Docker, rename `%LOCALAPPDATA%\Docker\run` and
  `%LOCALAPPDATA%\docker-secrets-engine` (for example to `run.stale-<date>`), start Docker Desktop. The
  `pgdata` volume survives; `docker compose up -d db redis` then works.
- Database holds 9,144 products, 2,655 safety-list rows (22,571 links) and 3,652 embedded knowledge
  chunks. Safety lists on disk: safety-alert 276, drugs-circulars 146, safety-labeling 241, rmm 578,
  drug-shortage 723, drug-shortage-resolved 586, dhpc 105 rows; all detail pages and PDFs present.
  A list's "gap" in its manifest (3, 7, 20) equals the number of rows the site repeats with identical
  content, so nothing was found missing. The other lists (approvals, pharmacies, unregistered,
  vet-drugs, feed, and so on) have no records on this machine; drug-companies has 6,135 rows that are
  not loaded.
- Assistant: follow-up questions work when the app sends `history`; model citation marks like
  `【9†L1-L5】` are now cleaned; a provider rate limit (free Groq tier: 8,000 tokens a minute) answers
  HTTP 429 "busy" instead of 500.
- Phone: `.claude/launch.json` has a `phone` entry; the app reads the API address from
  `mobile/.env.local` (`EXPO_PUBLIC_API_URL`, git-ignored, change the IP when the network changes).

### 15b. Pictures, voice search and roles (2026-11-21)

- Picture files were lost in the machine move (the mapping and `images.jsonl` survived).
  `pharmavique sfda-images-restore` downloads the 2,964 mapped real pictures again from their recorded
  URLs (polite: robots.txt, one throttle per host) and keeps a file only if its sha256 equals the
  recorded `content_hash`. Files live in `data/media/images/` (git-ignored). Then
  `sfda-pictures-load` writes `catalog.product_pictures` (2,964 real, 6,198 generated) and the API
  serves `GET /v1/products/{register}/picture` (404 for generated cards: the app draws a placeholder).
  1,922 of the real pictures are `needs_review`; the header `X-Picture-Status` says which.
- Voice search: `POST /v1/voice/drug-name` takes the transcript and returns the drug name to search
  for (the chat model, rules as the fallback), so "أنا عايز بنادول" searches "بنادول".
- The app asks who is using it on first launch (patient, pharmacist, company or warehouse owner),
  kept on the device only; no sign-in yet. The role picks the assistant's answer level and suggestions.
