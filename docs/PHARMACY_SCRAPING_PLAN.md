# Saudi pharmacy catalog scraping: plan, first findings and questions

Status: **plan for approval, no scraper code written yet.** Date: 2026-11-23. Owner request: collect the
public catalogs of 50 Saudi online pharmacies (products, prices, availability, image URLs, ingredients
where the page states them), refreshed every day, as a section of its own inside Pharmavique.

Working agreement (CLAUDE.md): plan first, assumptions and questions listed, wait for approval before code.

## 1. What the project already has (Phase 1)

| Area | What exists | Consequence for this work |
|---|---|---|
| Registry | `catalog` context: one `Product` per SFDA register number, one official `ListedPrice` and an append-only price history | The registry price is the **official** price. A pharmacy's shelf price is a different thing and must not overwrite it |
| Pharmacies | `catalog.domain.pharmacies` and `api_pharmacies`: **physical** pharmacies from SFDA lists, with locations | No concept of an online pharmacy listing, a retailer price or a retailer image URL |
| Crawl plumbing | `ingestion` context: `PoliteFetch` (robots.txt, one request at a time, stop on a block), Playwright fetcher, list walker, snapshot store, resumable runs | Reusable for polite fetching and run bookkeeping |
| Scheduling | GitHub Actions `daily-refresh.yml` (Linux, about two hours, Neon as target) and the Windows task | The new daily run fits the same workflow, as its own job, so one failure cannot stop the SFDA refresh |
| Pictures | `media` context downloads pictures found on shops into `data/media` and serves them from the Neon bucket | This request is different: **URLs only, no downloads**. Both can live side by side |
| Matching | `catalog.domain.list_linking`, `search` (normalized names, Arabic), `substitution` (equivalence rules) | Reuse `core_name`, `normalize_text` and the equivalence rules; do not write a second matcher |
| Rules that apply | One Postgres schema per context, no cross-context imports (import-linter), every record has provenance and a trust level, never assume currency, never invent data | A listing is `unofficial_unverified`, carries its source URL and fetch time, and keeps the currency the page states |

## 2. Proposed shape (needs your approval, ADR-019 to write)

A new context **`offers`** (the pharmacy-specific side), next to `catalog` (the canonical side):

- `Retailer`: a pharmacy website (domain, name, market, platform, validation status, last success).
- `Listing`: one product on one retailer: source product id, URL, names (en/ar), brand, category path,
  barcode if shown, ingredients **as the page states them** (original text kept, normalized value separate).
- `ListingPricePoint`: price, original price, discount, currency as stated, observed at. Written only when it changes.
- `ListingAvailability`: in stock or not, as the page says, checked at. Never a quantity unless the page exposes one.
- `ListingImage`: URL, alt text, role (main or extra), last check status. **No file is downloaded or stored.**
- `ListingMatch`: link to a canonical register number with the evidence and a status (`matched`, `possible`,
  `needs_review`). Uncertain matches stay `possible`, never merged silently.
- `ScrapeRun`: per retailer counters (discovered, new, changed, failed, missing price, bad image URLs, duration).

Why a new context and not `catalog`: the registry is official and about one product per register number; listings
are many per product, unofficial and change daily. Putting them together would break the "canonical vs
pharmacy-specific" separation the request asks for, and `catalog` would need to import retailer concepts.
It costs one new schema, one migration set, one import-linter contract and an ADR.

One adapter per retailer (`offers/infrastructure/retailers/<name>.py`) behind one port, each testable with saved
real pages (fixtures captured from the live site, not invented).

## 3. First findings on the Priority A sites (Phase 2, partly done)

Method: one polite request at a time (2 s apart), the project's User-Agent, `robots.txt`, the home page,
platform hints in the HTML. 2026-11-23. Platform hints are heuristics, not proof.

| # | Site | robots.txt | Home page | Hints | Sitemap in robots.txt | Verdict so far |
|---|---|---|---|---|---|---|
| 1 | nahdionline.com | 200 | 200 | Magento, Next.js, JSON-LD | yes (EN/AR/UAE) | Promising. The UAE sitemaps show the domain also serves another market: Saudi pages must be told apart |
| 2 | al-dawaa.com | **403** | **403** | behind Cloudflare | none readable | **Blocked for automated clients, even robots.txt.** Not scrapable without their permission |
| 3 | unitedpharmacy.sa | 200 | 200 | Magento, JSON-LD, Cloudflare | yes (EN/AR) | Promising |
| 4 | innovapharmacy.com | 200 | 200 | Magento, Next.js, JSON-LD | yes (products, categories, brands) | Promising |
| 5 | almujtamapharmacy.com | 200 | connection error | unknown | none | Home page failed twice in the probe: retry from another angle before judging |
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

Not yet checked: that each site really serves Saudi Arabia with a product catalog, its categories, whether a public
JSON endpoint exists, and Priority B (35 candidates, many without a URL). The brief asks for 50 validated sources:
that is only true after this check, and some candidates (for example `boots.com`, `binsina.ae`, `lifepharmacy.com`)
may serve other markets or not be independent pharmacies.

**Hard rule applied:** a site that answers 403 to a plain request is not bypassed. It is listed as blocked and replaced,
unless the owner gets permission from the pharmacy.

## 4. Assumptions

1. Only public pages and public JSON endpoints, `robots.txt` honored, one request at a time per site, a clear User-Agent, cache.
2. No login, no CAPTCHA solving, no anti-bot evasion. A blocked site is a rejected source.
3. Prices are stored in the currency the page states (expected SAR), with the page's text kept; a missing currency is `unconfirmed`.
4. Ingredients come only from the page. An ingredient is never guessed from a brand name.
5. Retail listings are `unofficial_unverified` and never replace SFDA data.
6. Proof of concept status (project memory): no legal review gate until the owner says production. Pharmacy
   terms of use still need reading per site before its adapter is called supported.
7. Image URLs only: no download, no Base64, no binary in the database. Hotlinking may be refused by some sites:
   that is recorded per image, and the app can show a placeholder instead.

## 5. Questions for the owner (answers change the work)

1. **New context `offers`** (section 2): approved? (Alternative: extend `catalog`, which I advise against.)
2. **Blocked sites** (Al-Dawaa, Lemon, Kunooz, and Dawi's pages): replace them, or do you have permission or an API key from them?
3. **Where should the daily run live**: a second job in the existing GitHub workflow (free, about two hours already used by the SFDA refresh), or its own workflow? Fifty sites daily may exceed the free runner time; sharding by site is possible.
4. **Neon free storage (1 GB, already used)**: a full catalog of 50 sites is hundreds of thousands of listings. Do we keep only listings matched to an SFDA register number plus the rest in a compact form, or is another database acceptable?
5. **Scope of "all products"**: the registry covers medicines. Cosmetics and devices have no register number here. Store them as listings with no canonical product, or skip them in the first release?
6. **Order**: after approval I would build the adapters for the Magento sites first (several share one structure), then Salla, then the rest.

## 6. Next steps once approved

1. ADR-019, migration, domain and ports with tests.
2. Finish the Priority A validation, then Priority B, and write the validation report (`docs/PHARMACY_VALIDATION.md`).
3. First five adapters, run for real, inspect the data, then the others.
4. Matching, price history, daily job, monitoring counters.
