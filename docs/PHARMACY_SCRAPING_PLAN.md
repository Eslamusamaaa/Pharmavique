# Saudi pharmacy catalog scraping: plan, first findings and questions

Status: **revised plan (v3: adds the database design and the phased execution plan), no scraper code written
yet.** Date: 2026-11-23.
Owner request: collect the public catalogs of Saudi online pharmacies (products, prices, availability, image
URLs, ingredients where the page states them), refreshed regularly, as a section of its own inside
Pharmavique. Owner's verdict on v1: "fundamentally approved", with the new `offers` context accepted and eight
revision requirements (sections 3 to 11 answer them one by one). Decision record: `docs/adr/ADR-019-offers-context.md`
(proposed).

Working agreement (CLAUDE.md): plan first, assumptions and questions listed, wait for approval before code.
Numbers marked **[assumption]** are guesses to be replaced by measurements from the first real crawls; numbers
marked **[measured]** come from our own database on 2026-11-23.

## 1. What the project already has

| Area | What exists | Consequence for this work |
|---|---|---|
| Registry | `catalog` context: one `Product` per SFDA register number, one official `ListedPrice`, append-only price history | The registry price is **official**. A pharmacy's shelf price is a different thing and never overwrites it |
| Physical pharmacies | `catalog.domain.pharmacies`, `api_pharmacies` (SFDA lists, locations) | No concept of an online listing, a retailer price or a retailer image URL |
| Crawl plumbing | `ingestion`: `PoliteFetch` (robots.txt, one request at a time, stop on a block), Playwright fetcher, resumable runs | Reused for polite fetching and run bookkeeping |
| Scheduling | GitHub Actions `daily-refresh.yml` (cron 01:00 UTC, timeout 330 min, Neon as target, `concurrency` group) | The offers jobs get their **own workflow** and concurrency group (section 7) |
| Pictures | `media` downloads pictures into `data/media` | Offers store **URLs only**; the two live side by side |
| Matching | `catalog.domain.list_linking`, `search` (Arabic normalization), `substitution` (equivalence rules) | Reuse `core_name`, `normalize_text` and the strength and form-family rules; no second matcher |
| Rules | One schema per context, no cross-context imports, provenance and trust on every record, never assume a currency | Listings are `unofficial_unverified`, carry source URL and fetch time, keep the currency the page states |
| Measured sizes | Local database 271 MB; `catalog.products` 9,186 rows = 29 MB (3.2 KB a row, jsonb); `catalog.price_history` 9,144 rows = 2.5 MB (about 270 B a row with indexes); `search.term` 34,651 rows = 16 MB | Used for the storage estimate (section 10) |

Registry facts that limit matching [measured]: the registry record has no barcode field (keys: agents, atc_codes,
authorization_status, description_code, distribution_site, dosage_form, ingredients, legal_status, manufacturers,
marketing_company, marketing_status, package, product_control, route, shelf_life, storage_conditions, trade_name).
So a barcode links listings **to each other** across pharmacies; it links a listing to the registry only if a
source that is proven to give the SFDA register number or a GTIN is found (open question D-6).

## 2. Architecture

New context **`offers`** next to `catalog` (canonical side). Reasons unchanged: the registry is official and one row
per register number; listings are many per product, unofficial and change daily.

```
src/pharmavique/offers/
  contracts/        queries for other contexts (best offers for a register number, retailer health)
  domain/           Retailer, Listing, ListingCategory, Lifecycle, PricePoint, Availability,
                    MatchEvidence, MatchStatus, AnomalyRule, reliability scoring (pure code)
  application/      DiscoverProducts, UpdateProducts, MonitorPrices, MonitorAvailability,
                    MatchListings, ApplyRetention, RetailerHealth; ports: RetailerAdapter, ListingStore, Clock
  infrastructure/   platforms/  magento.py salla.py shopify.py jsonld_generic.py
                    retailers/  <id>.py only when a site cannot be expressed as configuration
                    persistence/ (schema `offers`), migrations/
  presentation/     read-only HTTP: /v1/offers/..., event subscribers
config/retailers/   one TOML file per retailer (section 7)
```

Rules kept: `domain` and `application` import no framework and no other context; `offers` reads canonical data only
through `catalog.contracts` and `substitution.contracts` (allow-listed adapter module); no cross-schema foreign
keys or joins; `bootstrap` wires. Because of the last two rules `offers` can later live in **its own database**
(section 10), which is the main storage escape.

### 2.1 Four logical monitors (requirement 2)

| Job | Question it answers | Input signal | Frequency | Writes |
|---|---|---|---|---|
| **Discover** | Which product URLs exist? | sitemap index and sitemaps (`lastmod`), category pages as fallback | daily for the sitemap diff (a handful of requests); full re-walk weekly | new `Listing` rows, URL set |
| **Update** | Did a product's details change (name, ingredients, images, category)? | URLs whose sitemap `lastmod` changed; conditional GET with `ETag` / `If-Modified-Since` when the site honors it | daily, only changed URLs | `Listing` fields, `listing_revision` only when a field changed |
| **Price watch** | Did the price change? | list/category pages or a public JSON/JSON-LD source that shows price for many products per request; product page only when none exists | tiered (below) | `PricePoint` only on change (or anomaly) |
| **Availability watch** | In stock or not, as the page says? | same response as price watch whenever possible (one fetch, two readers) | same tier as price | `Availability` current state plus a change row |

Tiers for price and availability: **tier 1** every day (listings matched to a registered medicine, plus any listing
somebody watches); **tier 2** a rolling seventh of the remaining listings per day (so each is seen weekly).
Cosmetics and devices are tier 2 only. A full catalog crawl by product page happens **once** per retailer (the
initial load) and again only when discovery shows more than 30 percent new URLs [assumption] or a platform change.

Never fetched unnecessarily: a URL whose `lastmod` did not change and whose last conditional GET answered 304 is
skipped by Update; Discover costs only the sitemap files.

### 2.2 Database design (schema `offers`, one migration set, reversible)

No foreign key leaves the schema: `register_number` is plain text, resolved through `catalog.contracts`.
All enums are `text` with a `CHECK`. All timestamps are `timestamptz`. Sizes are in section 10.

| Table | Rows (pilot / 50) | Columns (key ones) | Keys and indexes |
|---|---|---|---|
| `retailer` | 10 / 50 | `id` (slug, PK), `name`, `base_url`, `platform`, `market`, `currency` (null = unconfirmed), `status` (`candidate`, `validated`, `active`, `paused`, `blocked`, `retired`), `paused_reason`, `config_hash`, `validated_at` | PK `id` |
| `listing` | 60k / 300k | `id` (identity, PK), `retailer_id` (FK), `source_id` (the retailer's SKU or product id), `url`, `name_en`, `name_ar`, `brand`, `category`, `category_path`, `ingredients_text`, `dosage_form_text`, `pack_text`, `barcode` (null), `image_urls text[]`, `status`, `status_changed_at`, `first_seen_at`, `last_seen_at`, `source_lastmod`, `etag`, `last_modified`, `content_hash` (16 bytes), `tier` (1 or 2), **current** `price_amount numeric(12,2)`, `price_currency`, `price_observed_at`, **current** `availability`, `availability_observed_at` | PK `id`; unique `(retailer_id, source_id)`; unique `url`; `(retailer_id, status)`; `(retailer_id, tier, price_observed_at)` for the rolling watch; partial `(barcode)` where not null; partial `(retailer_id)` where `category = 'medicine'` and `status = 'active'` for matching. No trigram or full-text index on names |
| `price_point` | 60k + changes | `listing_id` (FK), `observed_at`, `amount`, `currency` | PK `(listing_id, observed_at)`. Written only on change; the current price lives on `listing`, so reads never join |
| `availability_change` | small | `listing_id`, `observed_at`, `availability` | PK `(listing_id, observed_at)`. Written only on change |
| `price_month` | grows 1 row per listing per month after retention | `listing_id`, `month`, `min_amount`, `max_amount`, `last_amount`, `points` | PK `(listing_id, month)` |
| `listing_match` | 1 per medicine listing | `listing_id` (PK, FK), `register_number` (null), `status` (`matched`, `possible`, `needs_review`, `no_match`, `not_applicable`), `evidence jsonb` (the compared values and the verdict per field), `matcher_version`, `decided_at`, `reviewed_by`, `reviewed_at` | PK `listing_id`; `(register_number)` where status in (`matched`, `possible`); `(status)` where status = `needs_review` (the review queue) |
| `match_conflict` | small | `listing_id`, `register_number`, `reason` (`strength`, `form`, `ingredients`) | PK `(listing_id, register_number)`. So a conflicting pair is never proposed again |
| `price_anomaly` | small, 30-day life | `id`, `listing_id`, `observed_at`, `old_amount`, `new_amount`, `rule`, `state` (`quarantined`, `confirmed`, `rejected`), `resolved_at` | PK `id`; `(state)` where quarantined |
| `scrape_run` | 4 per retailer per day | `id`, `retailer_id`, `job_type` (`discover`, `update`, `price`, `availability`), `shard`, `started_at`, `finished_at`, `status` (`complete`, `partial`, `failed`, `blocked`), `requests`, `discovered`, `new`, `changed`, `unchanged`, `failed`, `missing_price`, `bad_images`, `completeness numeric(4,3)`, `error_classes jsonb`, `cursor jsonb` (where a resumable run stopped) | PK `id`; `(retailer_id, job_type, started_at desc)` |

Two more tables carry what the owner wants to show on a product page (section 16):

| Table | Rows | Columns | Keys |
|---|---|---|---|
| `description_text` | one per **distinct** text | `hash` (16 bytes, PK), `text`, `language` | PK `hash`. Many pharmacies copy the manufacturer's text, so each distinct text is stored once |
| `listing_text` | only for `matched` and `possible` medicine listings | `listing_id` (PK, FK), `description_hash` (FK to `description_text`), `observed_at` | PK `listing_id` |

Descriptions are not stored for cosmetics, devices or unmatched listings: at 1 to 3 KB a text, 300,000
listings would cost 300 to 900 MB, more than the whole Neon Free limit.

Derived, not stored: `retailer_health` (a view over the last 14 `scrape_run` rows per retailer and job
type: last success, consecutive failures, success rate, share of listings with a price) and listing
`freshness` (now minus `price_observed_at`). Row-level security is not needed: nothing here is personal data.
Why the current price sits on `listing`: it removes a join from every read and avoids copying the latest
`price_point` into a second place; history is the append-only table next to it.

## 3. Product matching (requirement 1)

A listing is compared with registry products **only if its category is `medicine`** (section 9).

Evidence collected, each with its source text kept:

| Evidence | Compared with | Notes |
|---|---|---|
| Brand / trade name | `trade_name`, normalized Arabic and English, alias table | Misspellings tested |
| Active ingredients | `ingredients[].name`, normalized to the project's ingredient names | Only what the page states; never guessed from the brand |
| Strength per ingredient | `ingredients[].strength` + `unit`, after unit normalization | mg vs g, mcg, IU, %, per-ml forms handled by one tested function |
| Dosage form | `dosage_form` through the existing form-family table | Tablet vs capsule vs syrup are different families |
| Package size | `package` | Count and unit parsed (30 tablets, 100 ml, 2 x 10) |
| Barcode (GTIN) | other listings only (section 1) | Same barcode on two retailers links them; a barcode that maps to two different products is flagged |

Statuses (stored on the listing, with the evidence):

- `matched`: brand equals the trade name **and** ingredient set equal **and** every strength equal **and** form
  family equal **and** package size equal. Missing evidence on the listing side (for example no package size)
  can never produce `matched`.
- `possible`: no conflict, but at least one required piece is missing or only approximate. Shown to users as
  "possible match, check with a pharmacist".
- `needs_review`: several registry candidates fit equally, or the listing contradicts itself (title says 500 mg,
  attribute says 250 mg). Goes to a review queue; never shown as a match.
- `conflict`: **hard stop.** Any strength mismatch after normalization, or a dosage-form family mismatch, or a
  different ingredient set. A conflicting pair is never `matched` or `possible` and cannot be promoted by a score.
  The conflict is stored (so the pair is not re-proposed) but not displayed as a match.
- `no_match`: nothing fits.
- `not_applicable`: cosmetics, devices and anything not `medicine`.

No weighted score decides `matched`: it is an all-conditions rule in code (like equivalence), tested with a table of
real pairs from the registry, including near names with different strengths. Matches are recomputed when the
listing changes or the registry changes; a `matched` listing whose evidence changes drops back to `possible` until
re-verified.

## 4. Data lifecycle (requirement 3)

Listing status, one column plus `status_changed_at`:

| Status | Meaning | How it is reached |
|---|---|---|
| `active` | the page exists and offers the product | seen in a run |
| `unavailable` | the page exists but says out of stock / not purchasable | availability watch; the listing stays and keeps its price |
| `missing` | absent from the enumeration | **only after two consecutive complete runs** in which it was not seen |
| `discontinued` | the site says the product is gone (404/410 on its own URL, or a clear "discontinued" mark) | confirmed by a direct fetch of its URL in two runs, or a retailer-stated flag |

Protection against false "missing" (same spirit as `sfda-withdraw-absent`, and the 85 percent baseline rule):

1. A run is **complete** only if discovery finished all sitemap files and category pages without a block or
   unhandled error **and** the number of URLs seen is at least 85 percent of the retailer's baseline (median of the
   last 5 complete runs). Otherwise it is `partial` or `failed` and **no listing is marked missing**.
2. At most 2 percent of a retailer's listings (minimum 50) can turn `missing` in one run; above that the run is held
   and reported as an anomaly for review.
3. A `missing` listing is never deleted; if it reappears it becomes `active` again with the history intact.

Retention (defaults, to be approved, section 12):

| Data | Kept | Then |
|---|---|---|
| `PricePoint` | 180 days full resolution | one row per listing per month (min, max, last) |
| Price points of cosmetics and devices | 90 days | monthly aggregate |
| `scrape_run` rows | 90 days | one row per retailer per week (counters only) |
| Failed-fetch detail (url, status, error class) | 30 days | deleted; counts remain in the run row |
| Raw snapshots (HTML/JSON) | **never in Neon**; only as a short-lived workflow artifact or cache, 7 days | dropped |
| Quarantined anomalies | 30 days after resolution | deleted |
| `discontinued` listings | 365 days after status change | deleted, matches and prices with it |

Avoiding duplication: the listing stores only what the retailer says (its names, category path, ingredient text,
image URLs as one `text[]` column, price). It never copies canonical registry fields; a match is one row per listing
pointing at a register number with a small evidence `jsonb`. Image status is stored only when an image fails.
Price points are written on change only. No per-listing log lines in the database. No trigram index on listing names
(measured: `search.term` costs 470 B per term; 300,000 listings would add well over 100 MB). Matching looks up the
canonical side, not the other way round.

## 5. Data quality (requirement 4)

**Per-retailer crawl accounting.** Every run writes one `scrape_run` row per retailer and job type: status
(`complete`, `partial`, `failed`, `blocked`), counters (discovered, new, changed, unchanged, failed, missing price,
bad image URL), `completeness` ratio, duration, request count, error classes. Retailer health is derived:
last success per job type, consecutive failures, 14-run success rate. Three failures in a row, or any 401/403/429,
puts the retailer in `paused` until reviewed; a block is **never retried** (existing rule).

**Source reliability and freshness (shown with every offer).**

| Indicator | Definition |
|---|---|
| `observed_at` | when this price/availability was last read |
| `age` | now minus `observed_at`; the API marks an offer `stale` after 3 days (tier 1) or 10 days (tier 2) [assumption] |
| `reliability` | `high` / `medium` / `low` from the retailer's last 14 runs: success rate, share of listings with price, share of parse errors, share of anomalies. Thresholds fixed in code and shown in docs, not hidden |
| `trust` | always `unofficial_unverified` |

**Price anomaly detection** (rules in the domain, deterministic, no model):

1. Price missing, zero, negative or not a number: not stored as a price; counted as `missing price`.
2. Change of more than 50 percent against the previous price, or a ratio near 10, 100 or 0.1 (decimal slip):
   the new value goes to **quarantine**, the old price stays current, and it is accepted only when a second
   observation (another run) confirms it.
3. Currency change on a retailer: whole run held, never converted.
4. Retailer-wide shift (more than 20 percent of a retailer's listings change in one run): run held for review
   (probably a parser or currency change).
5. Matched medicine far from the registry's official price: **flag only**, and only after the unit of the
   official price is confirmed (it is not today, Q-5), so this rule stays off until then.

## 6. Priority and validation order (requirement 7)

Phase 1 is **5 to 10 validated pharmacies**; the pipeline must be proven end to end before any expansion.

| Wave | Retailers | Gate to pass |
|---|---|---|
| Pilot | 5 from the Priority A table (section 12): Nahdi (UAE pages told apart), United, Innova, Adam, one Salla store | Real pages saved as fixtures; adapter tests; a full run; matching report reviewed by the owner |
| Prove | up to 10 | Three daily runs in a row with `complete` status, no manual repair; price anomaly report understood; storage numbers measured |
| Expand | 11 to 50 | Only after Prove passes. Each new retailer is configuration on an existing platform adapter when possible |

Validation per retailer (written to `docs/PHARMACY_VALIDATION.md`): serves Saudi Arabia, has a product catalog,
robots.txt allows the paths, no block, a sitemap or public listing source, how price and stock are exposed, terms of
use read, sample of 20 pages checked by hand against the site.

## 7. Scalability: 50+ pharmacies without architectural change (requirement 5)

**Platform adapters plus retailer configuration.** Most Saudi stores run a handful of platforms (Magento, Salla,
Shopify, Zid, custom Next.js). A platform adapter knows how to enumerate and parse that platform; a retailer is a
TOML file:

```toml
id = "united"
name = "United Pharmacy"
base_url = "https://www.unitedpharmacy.sa"
platform = "magento"
market = "SA"
currency = "SAR"            # only if the site states it; otherwise unset and the price is `unconfirmed`
sitemaps = ["https://.../sitemap.xml"]
min_interval_seconds = 2.0
languages = ["en", "ar"]
[categories]                # retailer category path -> listing category
"Medicines" = "medicine"
"Skin Care" = "cosmetic"
"Medical Devices" = "device"
```

Adding retailer number 51 is a file plus fixtures; no code unless the platform is new. A retailer that cannot be
described by configuration gets a small `retailers/<id>.py` override, not a new architecture.

**Isolation from the SFDA daily refresh.** Own workflow `offers-refresh.yml`, own `concurrency` group, own
artifacts. A failure, timeout or block in offers cannot stop `daily-refresh.yml`, and the reverse. The offers jobs
write only to schema `offers`.

**Sharding.** One matrix job per retailer (a request budget of one at a time **per site**, sites run in parallel,
so a slow site never delays another). A very large site can be split into resumable chunks of at most 3 hours:
a run keeps a cursor and continues the next day. Matching runs as its own job after the shards, over only the
listings that changed.

**Execution-time estimates [assumption: 1 request every 2 s per site, as in the probes; JSON/HTML without a
browser; list pages show 36 products]:**

| Site size (listings) | Initial load by product pages (once) | Discover (sitemaps) | Update (2 percent changed) | Price+stock watch by list pages, tier 1 + one seventh of the rest | Daily wall time |
|---|---|---|---|---|---|
| Small, 2,000 | 67 min | about 1 min | 40 pages, 1.3 min | about 56 pages if all, 2 min | **about 5 min** |
| Medium, 8,000 | 4.4 h | about 2 min | 160 pages, 5.3 min | about 223 pages if all, 7.4 min | **about 15 min** |
| Large, 25,000 | 13.9 h (over several runs of at most 3 h) | about 5 min | 500 pages, 17 min | about 695 pages if all, 23 min | **about 45 min** |

A site with no list-page prices needs a product page per tier-1 listing: matched medicines are a small fraction
(the registry has 9,186 products; a pharmacy sells perhaps 1,000 to 3,000 of them [assumption]), so that is
2,000 to 6,000 requests, about 1 to 3.3 hours: still inside one job. A Chromium-based site is roughly three times
slower [assumption]; the plan prefers JSON, JSON-LD or plain HTML.

Daily load: 10 medium sites about 150 runner-minutes, finished in about 15 minutes wall time because shards run in
parallel; 50 mixed sites about 750 runner-minutes. The repository is **public** [measured: `gh repo view`], where
GitHub's standard runners are free according to GitHub's documentation (to be re-checked before relying on it); the
number of parallel jobs allowed on the free plan limits the wall time (about 20 jobs, to verify). Risk and fallback in section 11.

## 8. Daily rhythm

01:00 UTC SFDA refresh (existing) and, independently, 02:00 UTC offers: discover and update first, then price and
availability watch, then matching, then retention, then a health summary written to `data/refresh/offers-ATTENTION.md`
like the SFDA one. Retention runs weekly, not daily.

## 9. Product scope (requirement 6)

Listing category, set from the retailer's category map and never from guesswork:

`medicine`, `cosmetic`, `device`, `other` (supplements, food, baby care, anything the map does not name),
`unclassified` (the retailer's category is not in its map; counted, reported, never matched).

- Only `medicine` listings enter SFDA matching. `cosmetic`, `device`, `other`, `unclassified` have status
  `not_applicable` and are stored in the same table with the category column (no second table).
- They are tier 2, get 90-day price retention, and carry no ingredient normalization beyond the text kept.
- The API and app always show the category, so a cosmetic is never presented as a medicine.
- Retailer categories that mix kinds (for example "Vitamins") are mapped to `other` unless the owner decides
  otherwise (decision D-4).

## 10. Storage on Neon Free (requirement 8)

Neon Free limits (from `docs/DEPLOY_VERCEL_NEON.md`, read 2026-11-22): 1 GB per project, 100 CU-hours a month,
compute sleeps after 5 minutes idle. Current use if Neon equals the local copy of the four copied schemas:
about 255 MB [assumption: Neon not yet measured, decision step "check Neon" is pending].

Unit costs: measured 270 B per price point with indexes (`catalog.price_history`). A listing row is estimated at
1.7 KB with its indexes [assumption]: 0.9 KB of text (urls, en/ar names, category path, ingredient text, image
URLs array), 0.5 KB of indexes (retailer+source id unique, url unique, status, match key), 0.3 KB of match evidence.
Change rate 4 percent of listings a day [assumption].

| Per pharmacy of 6,000 listings [assumption] | Size |
|---|---|
| Listings | 6,000 x 1.7 KB = 10.2 MB |
| Initial price points | 6,000 x 270 B = 1.6 MB |
| Daily changes | 240 x 270 B = 65 KB a day |
| Steady state of price history with 180-day retention | about 11.7 MB (5.8 MB with 90 days) |
| Run bookkeeping | under 5 MB a year |
| **Total per pharmacy at steady state** | **about 23.5 MB** (17.6 MB with 90-day retention) |

| Scenario | Offers data | With existing 255 MB | Fits 1 GB? |
|---|---|---|---|
| 5 pharmacies (pilot) | 118 MB | 373 MB | yes |
| 10 pharmacies | 235 MB | 490 MB | yes |
| 20 pharmacies | 470 MB | 725 MB | yes, tight with Neon's own overhead and growth of the registry |
| 50 pharmacies | 1.18 GB | 1.43 GB | **no** |

Free-plan break-even keeping 20 percent headroom: (1,000 - 255 - 200) / 23.5 = about 23 pharmacies (about 31 with
90-day retention). All inputs are guesses until the pilot reports real counts; the first week's measured sizes
replace this table.

**Growth watch.** `offers` writes its own size and per-table sizes into the run summary each day.

**Migration ladder (triggers by share of the 1 GB):**

1. 70 percent: tighten retention (90 days), drop price history for cosmetics and devices, drop `discontinued`
   after 180 days, confirm no unused index.
2. 85 percent: move schema `offers` to **its own Neon project** (its own 1 GB). Possible without code change in
   the design because no cross-schema joins exist: one setting `PHARMAVIQUE_OFFERS_DATABASE_URL` (falls back to
   the main database), migrations run against it, matching reads the registry only through contracts. Neon's
   terms on several free projects must be read first (open question D-8).
3. Archive: export price points older than the retention window as compressed files to the Neon bucket (5 GB free,
   per `DEPLOY_VERCEL_NEON.md`) and keep only monthly aggregates in the database.
4. Paid plan or another Postgres: decided by the owner with the measured numbers; the data is plain Postgres so
   `pg_dump` of schema `offers` is the whole move.

## 11. Risks

| # | Risk | Effect | Mitigation |
|---|---|---|---|
| R1 | A site blocks us or changes its terms (already 3 of 15 answer 403: Al-Dawaa, Lemon, Kunooz; Dawi blocks pages) | Lost source | Never bypass; replace the source; permission request is the owner's call |
| R2 | A site redesign breaks a parser | Wrong or missing prices | Fixtures from real pages; parse-failure rate per run; run held above a threshold; anomaly quarantine |
| R3 | A wrong match shows a different strength or form as the same product | Medical risk | All-conditions rule, hard `conflict` stop, review queue, "possible" wording, matched-only shown by default |
| R4 | A bad crawl marks real products missing | Offers vanish | Complete-run definition, 85 percent baseline, 2 percent cap, two runs, nothing deleted |
| R5 | Storage exceeds Neon Free before the pilot ends | Registry and offers both at risk | Measure from day one, ladder triggers at 70 and 85 percent, separate project is the escape |
| R6 | Workflow time or parallel-job limits (public repo: standard runners free per GitHub docs, to re-check) | Runs miss the night | Shard by retailer, resumable cursors, tiers cut the daily work, offers workflow isolated |
| R7 | Neon compute hours (100 CU-hours a month) used by nightly writes | Throttling of the app | Batch writes, write only changes, measure CU use in the pilot |
| R8 | Prices without a stated currency | Wrong currency shown | Currency only as the page states; otherwise `unconfirmed`, surfaced in the API |
| R9 | Hotlinked images refused or removed | Broken pictures | URLs only, failure recorded per image, placeholder in the app |
| R10 | Terms of use forbid scraping on some sites | Legal exposure | Proof-of-concept rule (no legal gate) still requires reading each site's terms before it is called supported; listed per retailer in the validation file |
| R11 | Retail data mistaken for official data | Misleading users | `unofficial_unverified` everywhere, category shown, freshness and reliability shown, official registry price never overwritten |
| R12 | Same site serves several markets (Nahdi's UAE pages) | Wrong-country prices | `market` check per URL pattern in config; pages of other markets rejected, counted |

## 12. First findings on the Priority A sites (probe of 2026-11-23, unchanged)

Method: one polite request at a time (2 s apart), the project's User-Agent, `robots.txt`, the home page, platform
hints in the HTML. Hints are heuristics, not proof.

| # | Site | robots.txt | Home page | Hints | Sitemap in robots.txt | Verdict so far |
|---|---|---|---|---|---|---|
| 1 | nahdionline.com | 200 | 200 | Magento, Next.js, JSON-LD | yes (EN/AR/UAE) | Promising. UAE sitemaps show the domain also serves another market: Saudi pages must be told apart |
| 2 | al-dawaa.com | **403** | **403** | behind Cloudflare | none readable | **Blocked for automated clients, even robots.txt** |
| 3 | unitedpharmacy.sa | 200 | 200 | Magento, JSON-LD, Cloudflare | yes (EN/AR) | Promising |
| 4 | innovapharmacy.com | 200 | 200 | Magento, Next.js, JSON-LD | yes (products, categories, brands) | Promising |
| 5 | almujtamapharmacy.com | 200 | connection error | unknown | none | Home page failed twice: retry before judging |
| 6 | adamonline.com | 200 | 200 | Magento, JSON-LD | yes | Promising |
| 7 | lemon.sa | **403** | **403** | Cloudflare | none readable | **Blocked** |
| 8 | orangepharmacy.sa | 200 | 200 | Magento and WooCommerce hints, JSON-LD | yes | Promising, platform unclear |
| 9 | kunooz.com | **403** | **403** | Cloudflare | none readable | **Blocked** |
| 10 | zahra.com.sa | 200 | 200 | Next.js | none | Possible, needs a closer look (no sitemap) |
| 11 | dawi.sa | 200 | **403** | WordPress sitemaps, Cloudflare | yes | robots.txt readable, pages blocked |
| 12 | alhayahonline.com | 200 | 200 | Next.js, JSON-LD | yes | Promising |
| 13 | drmovepharmacy.com | 200 | 200 | Salla, JSON-LD, Cloudflare | yes | Promising (Salla stores share a structure) |
| 14 | aldawasa.com | 200 | 200 | Salla, JSON-LD, Cloudflare | yes | Promising |
| 15 | pharma.care.sa | 200 | 200 | Magento and Zid hints, JSON-LD | yes | Promising, platform unclear |

Not yet checked: that each site really serves Saudi Arabia with a catalog, its categories, whether a public JSON
endpoint exists, and Priority B (35 candidates, many without a URL). "50 validated sources" is true only after that
check; some candidates (for example `boots.com`, `binsina.ae`, `lifepharmacy.com`) may serve other markets or not
be independent pharmacies.

**Hard rule:** a site that answers 403 to a plain request is not bypassed. It is listed as blocked and replaced,
unless the owner gets permission from the pharmacy.

## 13. Assumptions

1. Only public pages and public JSON endpoints, `robots.txt` honored, one request at a time per site, a clear
   User-Agent, cache, conditional requests where supported.
2. No login, no CAPTCHA solving, no anti-bot evasion. A blocked site is a rejected source.
3. Prices are stored in the currency the page states; a missing currency is `unconfirmed`.
4. Ingredients come only from the page, never guessed from a brand.
5. Retail listings are `unofficial_unverified` and never replace SFDA data.
6. Proof of concept: no legal review gate, but each site's terms of use are read before it is called supported.
7. Image URLs only: no download, no Base64, no binary in the database.
8. Every number marked [assumption] is replaced by a measurement from the pilot.

## 14. Decisions (all approved by the owner on 2026-11-23: "I approve all", D-1 to D-12)

| ID | Decision | Recommended |
|---|---|---|
| D-1 | ADR-019 as written (context `offers`, four monitors, TOML retailers, own workflow) | Approve |
| D-2 | Blocked sites (Al-Dawaa, Lemon, Kunooz, Dawi pages): replace them, or do you have permission from them? | Replace |
| D-3 | Pilot set of 5 retailers and the 10-retailer proof gate before expansion | Nahdi (Saudi pages only), United, Innova, Adam, one Salla store |
| D-4 | Category mapping of mixed categories (vitamins, supplements) to `other`, not `medicine` | `other` |
| D-5 | Retention defaults: 180 days of price points (90 for cosmetics and devices), 90 days of run rows, 365 days for discontinued | Approve |
| D-6 | May we try to find a barcode or SFDA register number on retailer pages as extra match evidence, and add a barcode-or-GTIN source if SFDA's detail pages show one? (Registry has no barcode today) | Yes, as evidence only, never alone |
| D-7 | Run location: separate workflow in the public repo (free runners per GitHub docs) | Yes |
| D-8 | Escape for storage: a second Neon project for schema `offers` at 85 percent, after the terms are read | Yes, decide at the trigger |
| D-9 | Anomaly thresholds (50 percent change, 20 percent retailer-wide, 2 percent missing cap, 85 percent complete run) | Approve as starting values, tune after the pilot |
| D-10 | Staleness limits (3 days tier 1, 10 days tier 2) and the reliability labels `high / medium / low` in the API | Approve |
| D-11 | Who reviews the `needs_review` queue and the phase 4 sample of 100 pairs: the owner, or a pharmacist? (An unreviewed `possible` is never shown as a match either way) | A pharmacist for the sample; the queue stays unshown until someone reviews |
| D-12 | Exit-gate thresholds of phases 3 and 5 (parse failures under 2 percent, 20 sampled listings per retailer, three clean daily runs) | Approve as starting values |
| D-13 | Pictures for registered products from pharmacy listings: **copy** the chosen picture into our own storage through the existing `media` pipeline (a picture on a shop's server can vanish or refuse us), or only link to the shop's picture? | Copy, only the one best picture per registered product, from a `matched` listing |
| D-14 | A pharmacy's description of a medicine is its marketing text and can be wrong: show it as "from <pharmacy>, not verified", with date; may the assistant quote it (always with that source) or not at all? | Show on the page with source; the assistant may quote it only as "the pharmacy states", never as a medical fact |
| D-15 | Searching inside the pharmacies' products: through the registry first (find the medicine, list the pharmacies that carry it), and a name search over active medicine listings only; no name index over all 300,000 listings (too large for Neon Free) | Yes |

## 15. Execution plan (phases, each with an exit gate; nothing starts before the previous gate passes)

Effort is relative (S: days, M: about a week or two, L: more), not a calendar promise; the pilot
measurements replace these guesses.

| Phase | Work | Size | Exit gate (all must hold) |
|---|---|---|---|
| 0. Approvals | The owner answers D-1 to D-10 (section 14); ADR-019 is accepted | S | Written answers; ADR status `accepted` |
| 1. Foundations (no network) | Schema `offers` and its migration (down and up work); domain rules: matching verdicts, lifecycle (complete-run definition, two-run missing rule, caps), anomaly rules, retention, reliability and freshness; ports; import-linter contract | M | Unit tests green for every rule above, including the table of real near-name pairs with different strengths and forms; `ruff`, `mypy`, `lint-imports` clean; migration reversible |
| 2. Validate the pilot retailers | For each of the 5 pilot sites: robots.txt, terms of use, Saudi market check, sitemap or listing source, how price and stock are exposed, 20 hand-checked pages; saved real fixtures; `docs/PHARMACY_VALIDATION.md` | M | 5 retailers pass the checklist, or are replaced; no blocked site in the set |
| 3. Pipeline on the pilot | Platform adapters and config for the pilot; discovery, update, price and availability jobs; initial load; run locally against real sites | L | Initial load of the 5 retailers finished as `complete`; parse failure rate under 2 percent of pages and 20 sampled listings per retailer match their pages (starting thresholds, D-9) |
| 4. Matching review | Run the matcher on the pilot's `medicine` listings; the owner (or a pharmacist) reviews 100 sampled pairs across `matched`, `possible`, `needs_review`, and the conflicts | M | No wrong `matched` in the reviewed sample; every conflicting strength or form ended as `conflict`; the report is in `docs/` |
| 5. Daily operation | Own workflow `offers-refresh.yml`, sharding by retailer, health and retention jobs, `offers-ATTENTION.md` summary, size and compute reporting | M | Three daily runs in a row `complete` for every pilot retailer without manual repair; SFDA refresh unaffected; measured storage and Neon compute hours written next to the section 10 estimate |
| 6. Prove gate and widen | Grow to 10 retailers; then waves of about 10 more (configuration on existing platform adapters wherever possible) | L, repeated | Each wave repeats the phase 2 checklist and one clean week of runs; the storage ladder (section 10) is re-evaluated before each wave |
| 7. Enrichment and product surfaces | Offers on the product page (price per pharmacy, availability, freshness); search of a medicine and the pharmacies that carry it; filling a registered product's missing picture and description from its `matched` listings (section 16) | M | The owner reviews 50 filled products (picture really shows that product and strength; description is the pharmacy's own words with its name and date); no `possible` listing ever fills anything |
| Later (separate approval) | Further app surfaces for offers (best offer for a medicine, freshness and reliability shown), Egypt retailers | | Not part of this plan |

Verification at every phase end follows CLAUDE.md: `ruff check`, `ruff format --check`, `mypy src tests`,
`lint-imports`, `pytest`, docs and ADR updated, migrations reversible, real outputs reported.

## 16. What the owner wants to do with it, and how the design delivers it

Goal (owner, 2026-11-23): with up to 50 pharmacies loaded (the largest in Saudi Arabia), see each
pharmacy's products, pictures, active ingredients and prices; search them; compare one medicine's price
across pharmacies; see what is available where; read the description of a medicine inside a pharmacy;
and use the match between a pharmacy's product and a registered (SFDA) product to fill the registered
product's missing **picture** and **description** (what it is for, how it is used).

| Wish | How the design delivers it | What it still needs |
|---|---|---|
| 50 pharmacies | Retailers are configuration over platform adapters; waves of 10 after the pilot of 5 to 10 (phase 6). The 50 is reached by waves, not in one step | The largest pharmacies are not all scrapable: 3 of the 15 first checked (Al-Dawaa, Lemon, Kunooz) refuse automated clients and are not bypassed (D-2). The list of "the largest 50" must come from a source the owner trusts; we have not found a published ranking |
| Each pharmacy's products, pictures, ingredients, prices | `listing` (names, ingredients text, picture URLs, current price) | Picture files themselves: D-13 |
| Compare one medicine's price across pharmacies | A registered product's `matched` listings, one per pharmacy, with price, currency, availability, freshness and reliability. Listings that are only `possible` are shown apart and labelled | Matching quality (phase 4 review) |
| See what is available where | `availability` on `listing`, with `observed_at` | Only what the page says; never a quantity |
| Search | D-15 | |
| Description of a medicine inside a pharmacy | `description_text` and `listing_text` (section 2.2) | D-14 |
| Fill a registered product's picture and description | Enrichment rule below | D-13, D-14 |

**Enrichment rule (phase 7).** For a registered product with at least one `matched` listing:

1. Picture: the best picture URL, chosen by retailer reliability (`high` first), then freshness, then
   an image whose URL answered correctly in the last check. A `possible` or `needs_review` listing never
   supplies a picture or a description. A registered product keeps its own picture if it has one.
2. Description: the text of the most reliable matched pharmacy, shown with the pharmacy's name and the
   date, marked unverified. Two pharmacies with different texts are both kept; the page shows one and
   offers the other.
3. Every filled field records its `listing_id`, so a wrong match can be undone and the field removed.
4. Similar medicines in several pharmacies are expected: they link to the same registered product through
   `matched` listings; their prices are then comparable. The same medicine in two pharmacies that
   cannot be tied to a register number (no match) can still be compared by barcode when both show one.

**Replaced approach.** Filling "what it is used for" from US drug-label text and WHO ATC classes
(started on 2026-11-23) is **dropped by the owner's decision of the same day**: descriptions will come
from the pharmacies' pages once they are scraped. The downloaded label files and ATC pages were deleted.
