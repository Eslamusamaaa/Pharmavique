# ADR-011: company views and the operator's quality board

Status: accepted, 2026-11-21 (owner asked for company screens and a data-quality board; decision D-5
in `docs/ARCHITECTURE.md`: `analytics` builds its own read tables, no views over other contexts' tables).

## Context

A drug company or a distributor wants to see how the registry looks around an ingredient: who sells
it, in which strengths and forms, at what registered price, which strengths few makers cover, and what
changed lately. The platform's operator wants to see what is missing in the catalog and whether the
daily refresh ran. The data is public registry data, not personal data.

## Decision

- **`analytics` owns a read model**, schema `analytics`: `market_products` (one row per product, with
  ingredients and strengths as stated, form, marketing company, price with currency and basis),
  `market_events` (one row per integration event) and `projection_meta`. No foreign keys to other
  schemas.
- **The read model is rebuilt, not patched.** `pharmavique analytics-rebuild` reads the catalog's full
  export (`CatalogDetailsExport` in `catalog.contracts`, through the one allow-listed adapter module)
  and swaps the rows in one transaction, so the API keeps answering from the old rows until the new
  ones are complete. The daily refresh runs it after the drugs load and the relay.
- **The radar comes from events.** The outbox relay now has two subscribers (watchlist, analytics).
  Analytics keeps price changes, withdrawals, relistings and new products, once per event id. An event
  older than the first rebuild is not counted (it is already part of the state), so the first load
  never floods the radar; the radar counts from the first rebuild.
- **Company endpoints** (`/v1/company/market`, `/gaps`, `/radar`) are for the `company` role and the
  operator. The market map and the gaps are computed in pure domain code
  (`analytics/domain/market.py`) from the rows of one ingredient.
- **No demand claims.** There are no sales or stock figures. A "thin" cell means few registered makers
  (default two or fewer); a "missing" cell is a strength and a form that both exist for the ingredient
  but never together, which may be meaningless clinically or legally. Both say so in the response.
- **Prices never mix.** A price range is formed only among prices with the same currency code and the
  same currency basis (`source_stated`, `owner_assumption`, `unconfirmed`), and the basis is always
  returned.
- **Strengths are as the source states them** (no unit conversion here); an ingredient without a
  strength is grouped as "not stated". Equivalence stays in `substitution`.
- **The quality board** (`GET /v1/operator/quality`, `operator` role only, read-only) combines three
  sources: counts from the catalog (`CatalogQuality` contract: listed products without price,
  ingredients, strength, manufacturer or picture; per official list, rows, matched, possible and
  unlinked links); the read model's status; and the daily refresh's own files
  (`data/refresh/<date>/summary.md` and `drugs-load.log`, read by `FileRefreshHistory`). What cannot
  be known (no refresh folder, no load log) is returned as unknown, never zero. "Rejected" and
  "skipped" come from the drug loader's report line, because the loader does not store them.
- Company views see registry data of the whole market, not only the company's own products: the
  `company` tenant has no link to a marketing-company name yet, and the data is public anyway.

## Consequences

- The company views are only as fresh as the last rebuild (daily). They answer 503 with a clear
  message until the migration and the first rebuild have run.
- The radar shows what changed, not why, and starts empty.
- A real company tenant (a `company` account tied to its registered marketing-company name, so it
  can see "my products" next to the market) needs an owner decision and a verification step; it is not
  built.
- The refresh files are local to the machine that runs the refresh. A deployed API on another machine
  reports the refresh as unknown until the summaries are shipped (or recorded in the database).
