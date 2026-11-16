# Project brief for Claude Code: Drug Intelligence Platform (Egypt + Saudi Arabia)

> How to use: save this file as `docs/PROJECT_BRIEF.md` in an empty repo, open Claude Code in that folder, and send the "FIRST MESSAGE" section at the bottom. Copy sections 1-9 into `CLAUDE.md` (shorten as needed) so every session keeps the rules.

---

## 1. What we are building

A multi-tenant platform built on official drug-registry data, with three user roles and one shared core:

- **Patient:** photographs a medicine box, the system identifies it, and returns pharmaceutically equivalent products (same active ingredients, same strength, same dosage form) sorted by price. Also: personal medicine list, duplicate-ingredient warning, plain-language leaflet explanation, price/availability alerts.
- **Pharmacist:** fast lookup by text, photo, or voice; equivalents when an item is out of stock; prescription-photo reading; price-change alerts for shelf items.
- **Pharma company:** market map per active ingredient (competitors, prices, strengths, forms), gap discovery, competitor radar (new, withdrawn, price-changed products), price comparison.

Markets: **Saudi Arabia (SA)** and **Egypt (EG)**. SA data is available through an official developer portal. EG data sources are still being investigated, so EG must be a pluggable adapter that can be added later without touching the core. If EG is blocked, ship SA first.

Expected scale: large numbers of concurrent end users (mostly read-heavy lookups), heavy bursts from photo recognition, and periodic bulk ingestion.

## 2. Architecture requirements

Use **Domain-Driven Design** with **Onion / Hexagonal architecture**, as a **modular monolith** first (strict module boundaries so any module can be extracted to a service later). Do not start with microservices; explain this decision in an ADR.

Layers (dependencies point inward only):

1. `domain`: entities, value objects, domain services, domain events. No framework imports, no I/O.
2. `application`: use cases (commands/queries), ports (interfaces), DTOs, transaction boundaries.
3. `infrastructure`: adapters (database, cache, queue, HTTP clients, LLM/VLM, object storage, source connectors).
4. `presentation`: HTTP API (FastAPI), auth wiring, request/response schemas.

Enforce the dependency rule automatically in CI (use `import-linter` contracts). A violation must fail the build.

Bounded contexts (each is a top-level module with its own domain/application/infrastructure):

| Context | Responsibility |
|---|---|
| `catalog` | Products, active ingredients, strengths, dosage forms, manufacturers, registrations, per-market listings, price history |
| `ingestion` | Source connectors per market, snapshots, normalization pipeline, diff engine, change events |
| `search` | Fuzzy and semantic search, Arabic/English normalization, aliases/transliteration |
| `substitution` | Equivalence rules and ranking (domain service), explicit and unit-tested |
| `recognition` | Photo to structured fields (trade name, strength, form, registration number, barcode) through a vision port, then matching |
| `knowledge` | Leaflet documents, chunking, embeddings, grounded retrieval with citations (RAG) |
| `identity` | Users, roles (patient, pharmacist, company), tenants (pharmacy, company), RBAC |
| `watchlist` | Personal medicine lists, alerts, notification preferences |
| `analytics` | Read models for the company view (market map, gaps, competitor radar) |

Patterns to apply where they earn their keep (justify each in an ADR, do not over-engineer):

- CQRS-lite: separate command and query handlers; analytics uses dedicated read models/materialized views.
- Domain events + **transactional outbox** for change events (`ProductAdded`, `ProductWithdrawn`, `PriceChanged`) feeding alerts and analytics.
- Ports and adapters for every external dependency, including the LLM/VLM provider (swappable), the source connectors, and the clock.
- Idempotent, resumable ingestion (a run can be retried safely).
- Repository pattern per aggregate; Unit of Work at the application layer.

## 3. Tech stack (propose changes only with an ADR)

- Python 3.12, `uv`, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + Alembic
- PostgreSQL with `pg_trgm` (fuzzy text) and `pgvector` (embeddings)
- Redis (cache, rate limiting), a job queue for ingestion and photo processing (Arq or Celery; pick one and justify)
- Object storage abstraction for images (local disk in dev, S3-compatible in prod)
- OpenTelemetry (traces, metrics), structured JSON logs
- Docker Compose for local dev; pytest, hypothesis for property tests of equivalence rules; ruff, mypy (strict on `domain` and `application`)
- Frontend is out of scope for now (API first). Later: Next.js with role-based views.

## 4. Scalability requirements

- Stateless API processes; horizontal scaling; all state in Postgres/Redis/object storage.
- Read path: cache hot lookups in Redis with explicit invalidation on ingestion; pagination and keyset pagination for large lists; indexes designed from real query plans (include `EXPLAIN` evidence in PRs).
- Write path: bulk ingestion through a worker, never in the request cycle; batch upserts; snapshot tables partitioned by date.
- Photo recognition: asynchronous job with a status endpoint (accept, queue, poll or webhook), per-user rate limits, back-pressure, and a timeout/fallback when the vision provider is slow.
- Multi-tenancy: tenant id on tenant-owned data (pharmacy inventory, personal lists); row-level isolation tested.
- Include a load-test plan (k6 or Locust) with target numbers to be agreed, and a documented path from modular monolith to extracted services.

## 5. Domain rules (the part that must be correct)

- **Equivalence** (substitution context): two products are equivalent only if they have the same set of active ingredients, the same strength per ingredient after unit normalization (mg vs g, per ml, etc.), and the same dosage-form family. Anything uncertain is returned as "possible, needs pharmacist check", never as equivalent. Encode this as pure domain functions with exhaustive tests, including combination products and unit conversions.
- Never present output as medical advice. The patient view must say the pharmacist or doctor decides; the system never recommends stopping or switching a medicine and never gives dosing advice.
- Every record carries **provenance**: source, source URL or file, fetched_at, snapshot id, and a `trust` level (`official`, `unofficial_unverified`).
- Do not assume currencies or price units. Read the source documentation and store `currency` explicitly per market; if undocumented, mark it `unconfirmed` and surface that in the API.
- LLM answers must be grounded: the RAG layer answers only from retrieved leaflet chunks or catalog data and returns citations; if nothing is retrieved, it says so.
- Arabic and English: normalize Arabic (diacritics, alef/ya/ta marbuta variants, Arabic-Indic digits), keep an alias table for trade names written in either script, and test with misspellings.

## 6. Data sources and compliance rules (important)

- **SA:** use the official SFDA developer-portal API with the user's own key, read from environment variables. Never hardcode, log, or commit keys. A third-party package reports the API may be restricted to Saudi IP addresses, so build a **file-import fallback** adapter (CSV/JSON dump obtained through SFDA's data-sharing request) behind the same port. Check the response schema from real calls; do not invent field names.
- **EG:** the official Egyptian Drug Database search sits behind a verification code (CAPTCHA). **Do not scrape it and do not try to bypass the CAPTCHA.** Build the EG connector as a port with an initial CSV-import adapter for a third-party dataset marked `unofficial_unverified`, and leave room for an official data feed obtained by request from the Egyptian Drug Authority. The official Egyptian database page does not appear to show actual prices, so EG price source is an open question tracked in `docs/OPEN_QUESTIONS.md`.
- Respect each site's terms of use and robots rules; throttle all outbound requests; identify the client with a clear User-Agent; cache aggressively.
- Terms found so far limit use of the SFDA site to internal business or personal use, so commercial use of scraped page content is a legal risk. Prefer the official API or a data-sharing agreement, and record the license status of every source in `docs/DATA_SOURCES.md`.
- Health-related user data (medicine lists, prescription photos) is sensitive: collect the minimum, encrypt at rest, set retention limits (delete uploaded images after processing unless the user opts in), keep it out of logs, and flag the need for legal review under the applicable data-protection laws in each country before launch.

## 7. Delivery phases

- **Phase 0, foundations:** repo scaffold, tooling, CI, import-linter contracts, Docker Compose, `docs/` with architecture overview, context map, ADRs, glossary, open questions, data sources.
- **Phase 1, SA catalog:** `catalog` + `ingestion` for SA (API adapter and file fallback), normalization, snapshot + diff + change events, trigram search, equivalents endpoint, REST API with OpenAPI, tests.
- **Phase 2, EG as a second market:** connector, market-aware queries, cross-market name mapping ("what is this called in the other country").
- **Phase 3, recognition:** photo to fields to match, async jobs, confidence thresholds, a labeled test set of real boxes.
- **Phase 4, knowledge (RAG):** leaflet ingestion, embeddings, grounded answers with citations, evaluation set.
- **Phase 5, roles and views:** identity, RBAC, patient list and duplicate-ingredient warning, pharmacist tools, alerts.
- **Phase 6, analytics:** company market map, gap discovery, competitor radar.
- **Phase 7, hardening:** load tests, observability dashboards, security review, backup/restore drill.

## 8. Working agreements

- Plan before coding. For each phase: write the plan, list assumptions and questions, wait for approval.
- One ADR per significant decision in `docs/adr/` (context, options, decision, consequences).
- Domain code first, with tests before adapters. Target high coverage on `domain` and `application`; every bug fix starts with a failing test.
- Small, reviewable commits with clear messages. No unrelated refactors.
- Never fabricate data, API fields, endpoints, prices, or medical facts. If something is unknown, write it in `docs/OPEN_QUESTIONS.md` and ask.
- Run lint, type checks, and tests before declaring any task done, and report the real output.
- No secrets in the repo. Provide `.env.example` only.

## 9. Definition of done for any task

Tests pass, lint and mypy pass, import-linter contracts pass, docs and ADRs updated, migrations included and reversible, and the change is explained in a short summary with any open risks.

---


