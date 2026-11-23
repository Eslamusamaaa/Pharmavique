# ADR-019: a separate `offers` context for online pharmacy listings

Status: **accepted**, 2026-11-23. The owner approved decisions D-1 to D-12 of
`docs/PHARMACY_SCRAPING_PLAN.md` section 14 in full ("I approve all"). Implementation follows the phases of
section 15 of that plan, one exit gate at a time.

## Context

The owner wants the public catalogs of Saudi online pharmacies (price, availability, image URLs, ingredients as
the page states them) refreshed regularly, starting with 5 to 10 validated pharmacies and designed to reach 50 or
more. The registry (`catalog`) is official, one product per SFDA register number. A pharmacy listing is
unofficial, many per product, and changes often. Medicines, cosmetics and devices all appear in the same shops;
only medicines can be matched to the registry. Neon Free holds 1 GB, and about 255 MB is probably in use.

## Decision

1. **New context `offers`** with its own Postgres schema `offers`, layers `contracts / domain / application /
   infrastructure / presentation`, import-linter contract and migrations. `catalog` imports nothing from it.
2. **Aggregates:** `Retailer`, `Listing` (one product on one retailer, with `category` in `medicine | cosmetic |
   device | other | unclassified` and `status` in `active | unavailable | missing | discontinued`), `PricePoint`
   (written on change only, price and currency exactly as stated, an unstated currency is `unconfirmed`),
   `Availability`, `ListingMatch` (status `matched | possible | needs_review | no_match | not_applicable`
   with its evidence; a hard `conflict` is kept in its own small table so the pair is not proposed again),
   `ScrapeRun` (per retailer and job type). The **current** price and availability sit on the `listing`
   row; history is append-only beside it. The table-level design (columns, keys, indexes, retention) is
   `docs/PHARMACY_SCRAPING_PLAN.md` section 2.2.
3. **Four monitors**, separate use cases: Discover (sitemaps), Update (changed pages, conditional requests),
   Price watch and Availability watch (one fetch may feed both readers). Tiers decide how often a listing is read.
   A full product-page crawl happens once per retailer.
4. **Matching is an all-conditions rule in code, not a score:** `matched` needs equal brand, ingredient set,
   strength per ingredient (after unit normalization), dosage-form family and package size. Any strength, form or
   ingredient conflict is `conflict` and can never become a match. Missing evidence gives `possible`; ambiguity or a
   self-contradicting listing gives `needs_review`. Only `medicine` listings are compared with the registry. A
   barcode links listings to each other; the registry has no barcode field today.
5. **Lifecycle safety:** a listing becomes `missing` only after two consecutive **complete** runs (all sitemaps
   and category pages read, at least 85 percent of the retailer's baseline), at most 2 percent of a retailer's
   listings (minimum 50) per run, and nothing is deleted at that point. A failed or partial run changes no status.
6. **Data quality:** `observed_at`, staleness and a reliability label per offer; per retailer success and failure
   accounting for every run and job type; deterministic price-anomaly rules with quarantine (a change over 50
   percent or a decimal-slip ratio waits for a second observation). Three consecutive failures or any 401/403/429
   pause the retailer; a block is never retried or bypassed.
7. **Retailers are configuration** (`config/retailers/<id>.toml`) over **platform adapters** (Magento, Salla,
   Shopify, JSON-LD generic). Code per retailer only for what configuration cannot express. 50 retailers need no
   architectural change.
8. **Isolation:** its own workflow `offers-refresh.yml` and concurrency group, one matrix job per retailer, writes
   only to schema `offers`. The SFDA `daily-refresh.yml` is untouched.
9. **Storage:** image URLs as one `text[]` column; raw pages never stored in the database; retention windows (price
   points 180 days full then monthly; 90 days for cosmetics and devices; run rows 90 days; discontinued 365 days);
   no trigram index on listing names. An estimate of about 23.5 MB per pharmacy of 6,000 listings (assumption)
   gives a Neon Free limit near 23 pharmacies. `offers` can move to its own database through
   `PHARMAVIQUE_OFFERS_DATABASE_URL` because no cross-schema keys or joins exist.

## Alternatives considered

- **Extend `catalog`.** Rejected: mixes official and unofficial data, many-per-product rows in an aggregate meant
  to be one-per-register-number, and `catalog` would depend on retailer concepts.
- **A score-based matcher.** Rejected: a high score can hide a strength or form conflict; the domain rule says
  uncertain is "possible, needs pharmacist check".
- **One adapter class per retailer.** Rejected: 50 sites of 5 platforms would mean 50 parsers to maintain.
- **Daily full crawl.** Rejected: 4 to 14 hours per medium or large site for no information gain; sitemaps and
  conditional requests answer "what changed" cheaply.
- **Storing pictures.** Out of scope here; `media` already does it for the registry. Offers keep URLs only.

## Consequences

- One new schema, migration set and import-linter contract; one more workflow to watch.
- Listing counts, change rates and run times in the plan are assumptions until the pilot measures them.
- The 85 percent baseline and 2 percent cap, the anomaly thresholds, the staleness limits and the retention
  periods are starting values, like Q-40 for the SFDA withdrawal limits; they are tuned from real runs.
- A matched offer is evidence of a listing, not a statement that two products are equivalent: equivalence stays in
  `substitution`.
- Blocked retailers (403 to a plain request) are replaced, not bypassed.
