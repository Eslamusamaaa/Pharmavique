# Phase 3 plan: accounts, alerts, company views, scale and the next features (DRAFT for approval)

Date: 2026-11-21. Builds on `README.md` (status and roadmap), `docs/FEATURES.md`, `docs/OPEN_QUESTIONS.md`,
ADR-001..008 and `CLAUDE.md`. Nothing here is built yet. Facts about the code were checked on
2026-11-21; anything about outside providers is an assumption until checked against their documentation.

## 1. What the owner asked for (2026-11-21)

Accounts and roles; alerts; company screens; the daily refresh scheduled; performance (cache, job queue,
load test); LASA name warnings; pharmacist shelf scan; compare two drugs; weekly digest; operator data
quality board; shortage to substitutes; allergies in "my medicines"; nearby pharmacies using the
patient's location; a "price changed" mark.

## 2. State of the code today (checked)

| Area | State |
|---|---|
| `identity`, `watchlist`, `analytics` | Empty packages: no Python files besides `__init__` |
| Outbox | Written by `catalog` in the same transaction as its changes. **No relay** reads it, so no other context hears about `ProductAdded`, `ProductWithdrawn`, `PriceChanged` |
| Comparison | `substitution/application/compare.py` exists; **no API route and no app screen** |
| Shortage and safety lists | Loaded and linked to products (`catalog/domain/list_linking.py`), so shortage to substitutes needs only a query and a screen |
| LASA | Only in docs. `shared_kernel` has the Arabic/Latin normalizer and pg_trgm-compatible trigrams, which the string part can reuse |
| Daily refresh | `scripts/daily_refresh.ps1` and `scripts/schedule_daily_refresh.ps1` exist; **not registered** on this machine |
| Redis | Used for rate limits and the audio cache only; no read cache for search or product pages; no job queue (ADR-002 chose Arq, not built) |
| Pharmacies | 385 rows with name, phone, address, region. **No coordinates** |
| Mobile | No `expo-location`, no push library. The role is kept on the device only |

## 3. Order and why

Dependencies decide the order, not the order of the request.

| Wave | Items | Needs |
|---|---|---|
| A | Shortage to substitutes; compare two drugs; LASA warnings; schedule the daily refresh | Nothing new. Can run in parallel |
| B | Accounts, tenants, roles (`identity`); sign-in on the API and app | Decisions Q-13, Q-14 (section 5) |
| C | Outbox relay; alerts; "my medicines" saved on the server with allergies; "price changed" mark; weekly digest | B for who gets what; the relay for events |
| D | Company screens: market map per ingredient, gap discovery, competitor radar; operator data quality board | B (roles), C (events feed the read models) |
| E | Redis read cache with invalidation on ingest; Arq job queue for scan and assistant; k6 load test | Independent of B-D, best after A so the load test covers real routes |
| F | Nearby pharmacies | Geocoding source and map choice (Q-23) |
| G | Pharmacist shelf scan | B (the pharmacy's shelf list), real shelf photos (Q-32), vision provider (Q-12) |

### Wave A

1. **Shortage to substitutes.** For a drug on the SFDA shortage list: `GET /v1/products/{n}/shortage` returns the
   shortage record (SFDA text, date, link) and the same-ingredient list with the existing verdict
   (`equivalent` or `possible, needs pharmacist check`). Screen: a banner on the drug page. Wording:
   "SFDA lists this drug as short; these have the same ingredients; ask your pharmacist". No "switch".
2. **Compare two drugs.** `GET /v1/products/compare?a=&b=` over the existing `compare.py`; screen with the two
   cards side by side: ingredient, strength, form, maker, registered price (with currency basis), status,
   safety items, verdict.
3. **LASA.** Offline job over the ~9,000 catalog names: string similarity (trigram) plus a phonetic key for
   Arabic and for English; writes candidate pairs to a review file; **a person approves the first list**
   (Q-26). API adds `similar_names` to the drug page; the scan lowers confidence when a name is confusable.
   Informational: "a similarly named drug exists".
4. **Schedule the daily refresh.** Registering a Windows scheduled task is a change to the machine, so the
   owner runs `schedule_daily_refresh.ps1 -Time 03:00` (or approves it). Check the summary files after the
   first night.

### Wave B: identity

- `identity` context: user, role (`patient`, `pharmacist`, `company`, `operator`), tenant (pharmacy,
  company), password hash, refresh token. Short-lived JWT plus refresh (Q-13 default). `Principal` in the shared
  kernel so other contexts read the caller without calling `identity` per request.
- Row-level security plus repository filters on tenant-owned tables (Q-14 default), with an isolation test
  that fails if one tenant can read another's rows.
- Search, drug pages and the assistant stay open without an account. An account is needed for saved
  medicines, alerts, shelf lists and company views.
- Minimum collection: email, password hash, role. No health data in the user row. Account deletion deletes
  the medicines list and alerts.
- App: sign-in and sign-up screens; the first-launch role choice becomes the account role.

### Wave C

- **Outbox relay** (`foundation`): reads unsent rows, publishes to subscribers, marks sent, retries, idempotent
  consumers keyed by event id.
- **Alerts.** `watchlist` subscribes to `ProductWithdrawn`, `PriceChanged` and new safety or shortage links;
  writes one alert per user whose list holds the product. First channel is an in-app list; the push channel
  sits behind a `NotificationSender` port (Q-18).
- **My medicines on the server**, with **allergies by active-ingredient name** (the user picks an ingredient
  from our catalog). A drug containing it shows: "contains X, which you recorded as an allergy; ask your
  pharmacist". Class allergies (penicillin to amoxicillin) are **not** done: no clinical source (Q-37).
- **Price changed mark** on the drug page and cards: last change date and old to new price from our own
  snapshots. Needs at least two refresh runs to show anything.
- **Weekly digest**: built from the structured diff only; a model may phrase it but never adds facts.

### Wave D

- `analytics` builds its own read tables from events (D-5): market map per ingredient (products, makers, strengths,
  forms, price range), gap discovery (strengths or forms sold by few makers), competitor radar (new,
  withdrawn, price-changed products per ingredient). Endpoints for the `company` role; screens in the app.
- Operator data quality board: counts of drugs without picture, without price, rejected rows, refresh run
  status and age, list gaps. Read-only, `operator` role.

### Wave E

- Redis read cache for `/v1/search` and product pages, key includes the data snapshot; invalidated by the
  ingest event. Measure hit rate.
- Arq queue behind the `JobQueue` port for scan and assistant, with a status endpoint, per-user limits and a
  timeout fallback (ADR-002).
- k6 scripts for search, product page, assistant and scan. **No target numbers are invented** (Q-11): the
  first run reports measured baselines; the owner then sets targets.

### Wave F: nearby pharmacies

- Geocode the 385 addresses **once, offline**, polite (one request a second, clear User-Agent, cached), store
  `lat`, `lon`, `geocode_source`, `fetched_at`, `trust = unofficial_unverified`. Rows that do not geocode
  stay without coordinates and are listed.
- `GET /v1/pharmacies/nearby?lat=&lon=&radius_km=`: the app sends the location **with the request only**;
  the server does not store it and does not write it to logs. The app asks for the foreground location
  permission and works without it (search by city or region instead).
- Result says "licensed pharmacy near you"; **never** that it has a drug in stock. Directions open in the
  phone's own maps app, so no maps SDK or key is needed for the first version.

### Wave G: shelf scan

Extend the box scan to many boxes in one photo: detect each box, read the name, match the registry, show a
grid; the pharmacist confirms; confirmed items become the pharmacy's shelf list (feeds alerts for that
pharmacy). Needs real shelf photos to measure honestly (Q-32); until then it ships behind a flag with the
confidence shown on every box. No stock counts, no availability claims. Photos are deleted after processing.

## 4. Rules that apply to every item

Equivalence only from `substitution` code; uncertain is "possible, needs pharmacist check". No dosing, no
"stop", no "switch". Every new record carries provenance and trust. Health data (medicines, allergies) and
location are sensitive: minimum collection, encrypted at rest, never logged, deleted on request.
Done means `ruff check`, `ruff format --check`, `mypy src tests`, `lint-imports`, `pytest` pass (real output
reported), docs and ADRs updated, migrations reversible. Tests before adapters; one commit per unit of work.

New ADRs: ADR-009 identity and tenancy, ADR-010 outbox relay and alerts, ADR-011 location handling.

## 5. Questions, each with the default I will use if told "go"

| ID | Question | Default |
|---|---|---|
| Q-13 | Own accounts or an external identity provider? Patient login method? | Own accounts, email and password, short-lived JWT plus refresh. Phone OTP later (needs an SMS provider and cost) |
| Q-14 | Tenant isolation | Row-level security plus repository filters |
| Q-18 | Alert channels | In-app list first; Expo push next behind the port |
| Q-23 | Maps provider and geocoding | One-time geocoding with OpenStreetMap's Nominatim (free, one request a second); directions through the phone's maps app; no key |
| Q-11 | Load targets | None invented; first run measures, you set the numbers |
| Q-9 | Legal review of health and location data | Not blocking development; **must happen before real users**, since accounts, medicine lists and location are now collected |
| New | Is an account required to use search and the assistant? | No: open; the account is for saved data only |
| New | Who is the first `operator`? | The owner's account, created by a CLI command, not by sign-up |

## 6. Progress

| Item | State (2026-11-21) |
|---|---|
| A1 Shortage to substitutes | Built: `GET /v1/products/{n}/shortage`, banner and flags on the drug page, tests |
| A2 Compare two drugs | Built: `GET /v1/compare`, compare screen, "قارن" button, tests |
| A3 LASA warnings | Built from names only (`search/domain/lasa.py`, `GET /v1/products/{n}/similar-names`, section on the drug page). **Unreviewed**: on the real catalog 1,133 of 4,859 distinct brands get at least one match (605 with a high one). A pharmacist should review a sample and tune the thresholds (Q-26). The scan does not use it yet |
| A4 Schedule the daily refresh | Needs the owner to register the task (see section 3) |
| B Accounts and roles | Built: `identity` context (scrypt passwords, JWT access tokens, rotating refresh tokens with replay detection), `/v1/auth/*`, `require_roles` guard, `create-operator` command, sign-in and account screens, [ADR-009](adr/ADR-009-identity-and-sessions.md). Integration tests pass on a real Postgres. Not yet done: row-level security (comes with the first tenant-owned tables in Wave C), a lockout per account |

## 7. Proposed start

Wave A first (four independent items, no decisions needed), then B, because C and D wait on it. After
approval Wave A can run as parallel sessions, one per item, each on its own files.
