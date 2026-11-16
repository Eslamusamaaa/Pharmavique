# Phase 1 Plan: SA Catalog

| | |
|---|---|
| Status | **Proposal, waiting for approval** |
| Date | 2026-11-16 |
| Scope | `catalog` + `ingestion` for SA (API adapter and file fallback), normalization, snapshot + diff + change events, trigram search, equivalents endpoint, REST API with OpenAPI, tests |
| Related | [ARCHITECTURE.md](ARCHITECTURE.md), [ADR-003](adr/ADR-003-search-strategy.md), [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) |

Working rule for every step below: tests first, domain before adapters, and a step is done only when ruff, mypy, import-linter and pytest all pass.

---

## 1. Assumptions (not facts)

1. A real SFDA sample (API response or data-sharing file) will be available before the SA adapters are written. Without it, no field names are invented (Q-4).
2. SA currency and price units are unknown until the source says so; they are stored as `unconfirmed` (Q-5).
3. Registry size is tens of thousands to low hundreds of thousands of rows per market. To be measured on real data in step 1.
4. Docker is available for integration tests. It is **not installed on the current machine**, so integration tests and the Arabic-trigram spike need Docker Desktop locally or must run in CI.
5. Per-market products first; cross-market mapping waits for Phase 2 (Q-15).

## 2. Steps, in order

Each step is one or more small commits.

| # | Step | Output | Depends on |
|---|---|---|---|
| 0 | **Spikes** (a) Arabic trigram check on the Docker Postgres image; (b) read a real SFDA sample | Spike notes in `docs/`, Q-4/Q-17 answered | Docker, SFDA sample |
| 1 | **Shared kernel**: `Market`, `Currency` (with `unconfirmed`), `Money`, `Provenance`, `TrustLevel`, event bases, `Clock`, `UnitOfWork`, `JobQueue` ports | Pure, strictly typed, unit-tested | none |
| 2 | **Foundation**: async DB session, Alembic env collecting per-context migrations, outbox table + relay + subscriber dedupe, JSON logging with scrubbing, readiness endpoint | Integration tests against Postgres | Docker |
| 3 | **catalog domain**: product, active ingredient, strength with unit normalization (mg/g, per ml), dosage-form family, registration, market listing, price history; hypothesis property tests on unit conversion | Domain tests, no I/O | 1 |
| 4 | **substitution domain**: equivalence as pure functions (same ingredient set, same normalized strength, same form family; uncertain gives "possible, needs pharmacist check"); exhaustive cases incl. combination products | Domain tests | 3 |
| 5 | **catalog application + infrastructure**: `ApplyCatalogChanges` (idempotent), queries, repositories, contracts, `ProductAdded` / `ProductWithdrawn` / `PriceChanged` via outbox, first migration | Integration tests | 2, 3 |
| 6 | **ingestion domain + application**: snapshot, ingestion run with batch checkpoints, diff engine (pure), idempotent and resumable run | Domain + application tests with fake ports | 1 |
| 7 | **ingestion infrastructure**: SA **file-import adapter first**, then SA API adapter once a real sample exists; normalization pipeline; `catalog_writer` adapter (first allow-list entry in import-linter) | Integration tests with fixture files | 5, 6 |
| 8 | **search**: Arabic/English normalizer (pure, with misspelling cases), projection built from catalog events, trigram adapter behind `SearchIndex`, labelled evaluation set (recall@k, MRR) | Evaluation report in the PR | 0a, 5 |
| 9 | **REST API + OpenAPI**: product search, product detail, equivalents; keyset pagination; responses expose provenance, `trust` and `currency` (including `unconfirmed`); medical-advice disclaimer on patient-facing payloads | API tests | 5, 8 |
| 10 | **Redis cache** for hot lookups with invalidation on ingestion | Integration tests | 9 |
| 11 | **Docs and CI**: `DATA_SOURCES.md`, `GLOSSARY.md`, ADR-004 (events and outbox), ADR-005 (persistence and tenancy), ADR-006 (ingestion idempotency); CI job with a Postgres service; `EXPLAIN` evidence for the main queries | Docs, green CI | all |

Steps 1, 3, 4 and 6 need no Docker or external data and can start immediately after approval.

## 3. Acceptance criteria

- Re-running the same ingestion twice produces no duplicate rows and no duplicate events.
- A run killed halfway resumes from its last checkpoint and ends in the same state.
- Equivalence never returns "equivalent" when any ingredient, normalized strength or form family differs or is unknown.
- Every returned record shows source, snapshot id, `fetched_at`, `trust`, and `currency` (possibly `unconfirmed`).
- Arabic misspelling cases in the evaluation set meet a recall@k threshold we agree on after the first measurement (no threshold is invented now).
- No secret appears in the repo or in logs.
- import-linter: 8 contracts kept, with only the real allow-list entries.

## 4. Open items that block parts of this phase

| Blocks | Question |
|---|---|
| Steps 0b, 7 (SA API adapter) | Q-4: SFDA key, IP restriction, real sample |
| Step 5 pricing fields | Q-5: SA currency and units |
| Step 0a, 2, 8 | Q-17 plus Docker availability |
| Step 9 SLOs, step 10 | Q-11: target numbers |
| Launch only | Q-8, Q-9: data license and legal review |

## 5. Risks

- **SFDA access restricted by IP** (reported by a third-party package): mitigated by building the file-import adapter first.
- **Arabic trigrams unusable with the DB locale**: caught by spike 0a before search code is written.
- **Boundary erosion under deadline pressure**: CI blocks it; allow-list changes are reviewed diffs.
- **Arq maintenance-only**: bounded by the `JobQueue` port and Postgres-authoritative state (ADR-002). No jobs are needed until Phase 3 except long ingestion runs.
