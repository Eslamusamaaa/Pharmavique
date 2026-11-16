# Repository Structure and Dependency Contracts (Proposal)

| | |
|---|---|
| Status | **Accepted and scaffolded (2026-11-16).** Package skeleton, 8 import-linter contracts (in `pyproject.toml`, TOML not INI as sketched below) and shape tests exist. The C3 allow-list starts **empty** with `unmatched_ignore_imports_alerting = "error"`; entries are added in Phase 1 together with the adapter that needs each one. The INI snippets below are the original proposal, kept for rationale |
| Date | 2026-11-16 |
| Related | [ARCHITECTURE.md](ARCHITECTURE.md) |

The package name `pharmavique` is a placeholder taken from the project folder (Q-2).

---

## 1. Folder tree

```
pharmavique/                           # repo root
├─ pyproject.toml                      # uv project, ruff, mypy, pytest, import-linter config
├─ uv.lock
├─ .env.example                        # no secrets, ever
├─ docker-compose.yml                  # postgres (+pg_trgm, pgvector), redis
├─ Dockerfile
├─ alembic.ini
├─ migrations/
│  └─ env.py                           # one Alembic env; version_locations = each context's migrations dir
├─ .github/workflows/ci.yml            # assumes GitHub; hosting not confirmed (Q-19)
├─ docs/
│  ├─ PROJECT_BRIEF.md
│  ├─ ARCHITECTURE.md
│  ├─ REPOSITORY_STRUCTURE.md
│  ├─ OPEN_QUESTIONS.md
│  ├─ DATA_SOURCES.md                  # to write: license status of every source
│  ├─ GLOSSARY.md                      # to write
│  └─ adr/
│     ├─ ADR-001-modular-monolith-vs-microservices.md
│     ├─ ADR-002-job-queue.md
│     └─ ADR-003-search-strategy.md
│
├─ src/pharmavique/
│  ├─ shared_kernel/                   # tiny, framework-free (ids, Market, Money/Currency, Provenance, Principal, event bases, technical ports)
│  ├─ foundation/                      # technical building blocks, no domain knowledge
│  │  ├─ db/                           #   engine, session factory, base UnitOfWork
│  │  ├─ outbox/                       #   outbox table helpers, relay, subscriber dedupe
│  │  ├─ events/                       #   bus, event registry, serialization, schema versions
│  │  ├─ queue/                        #   JobQueue adapter (per ADR-002)
│  │  ├─ cache/                        #   Redis, rate limiting, back-pressure
│  │  ├─ http/                         #   throttled client, User-Agent, caching
│  │  ├─ storage/                      #   ObjectStorage: local disk, S3-compatible
│  │  ├─ auth/                         #   JWT verification -> Principal
│  │  └─ observability/                #   OpenTelemetry, JSON logs, PII scrubbing
│  │
│  ├─ catalog/                         # <- every context has this exact shape
│  │  ├─ contracts/                    #   PUBLISHED LANGUAGE (only thing others may import)
│  │  │  ├─ queries.py                 #     Protocol + frozen DTOs
│  │  │  ├─ commands.py
│  │  │  └─ events.py                  #     integration events, schema_version
│  │  ├─ domain/
│  │  │  ├─ model/                     #     entities, aggregates, value objects
│  │  │  ├─ services/                  #     domain services
│  │  │  ├─ events.py                  #     internal domain events
│  │  │  └─ errors.py
│  │  ├─ application/
│  │  │  ├─ commands/                  #     command handlers (write side)
│  │  │  ├─ queries/                   #     query handlers (read side)
│  │  │  ├─ ports/                     #     repositories, gateways, UoW (interfaces)
│  │  │  ├─ event_handlers/            #     use cases triggered by events (context-local types)
│  │  │  └─ dto.py
│  │  ├─ infrastructure/
│  │  │  ├─ persistence/               #     SQLAlchemy models, repositories, mappers, read queries, UoW
│  │  │  ├─ adapters/                  #     outbound: other contexts' contracts, external services
│  │  │  └─ migrations/versions/       #     Alembic, branch label = context name, schema = context name
│  │  └─ presentation/                 #   inbound adapters
│  │     ├─ http/                      #     router.py, schemas.py, dependencies.py
│  │     ├─ inprocess.py               #     implements this context's contracts Protocols
│  │     └─ events.py                  #     integration-event subscribers (translate -> own commands)
│  │
│  ├─ ingestion/    (same shape; infrastructure/connectors/{sa_api,sa_file,eg_csv}/)
│  ├─ search/       (same shape; domain/normalization/ for Arabic/English rules)
│  ├─ substitution/ (same shape; domain/equivalence/ pure functions, no tables in Phase 1)
│  ├─ recognition/  (same shape; infrastructure/vision/ behind a vision port)
│  ├─ knowledge/    (same shape; infrastructure/embeddings/)
│  ├─ identity/     (same shape)
│  ├─ watchlist/    (same shape)
│  ├─ analytics/    (same shape; infrastructure/read_models/)
│  │
│  └─ bootstrap/                       # COMPOSITION ROOT: the only place that sees everything
│     ├─ settings.py                   #   env-driven config
│     ├─ container.py                  #   binds ports -> adapters
│     ├─ api.py                        #   FastAPI app factory, mounts each context's router
│     ├─ worker.py                     #   queue worker entrypoint, registers job functions
│     └─ outbox_relay.py               #   relay entrypoint
│
└─ tests/
   ├─ unit/<context>/{domain,application}/   # fast, no I/O; hypothesis property tests for equivalence
   ├─ integration/<context>/                 # real Postgres/Redis via compose
   ├─ contract/                              # contracts: DTO/event schema snapshot tests
   ├─ architecture/                          # rules import-linter cannot express (see section 3)
   ├─ e2e/
   └─ load/                                  # k6 or Locust plan; targets agreed first (Q-11)
```

Design notes:

- **`contracts/`** is the context's only public surface. It is a package, not a layer in the onion; it may import only `shared_kernel`.
- **`presentation/` is the inbound-adapter layer** (HTTP, the in-process implementation of `contracts`, event subscribers). This widens the brief's "HTTP API" wording **[Decision D-2]**.
- **Migrations travel with the context** (`infrastructure/migrations/`), so extracting a context carries its schema history with it. A single `migrations/env.py` at the repo root (outside the package, outside import-linter's scope) collects them through Alembic `version_locations` and branch labels. This must be validated while scaffolding.
- **`bootstrap/`** gives the stage-1 process roles for free (`api`, `worker`, `outbox_relay` from the same image).
- Python 3.12, `src/` layout so tests import the installed package, not the working directory.

---

## 2. import-linter contracts

These are a **draft for review**. Syntax and wildcard behavior will be validated against the installed import-linter version when the scaffold exists, and `lint-imports` must pass on the empty skeleton before any code is written.

```ini
[importlinter]
root_packages =
    pharmavique
    sqlalchemy
    fastapi
    pydantic
    redis
    arq
    httpx
    alembic
    opentelemetry
include_external_packages = True
```

### C1. Onion layers inside every context

```ini
[importlinter:contract:onion-layers]
name = Dependencies point inward inside each bounded context
type = layers
layers =
    presentation
    infrastructure
    application
    domain
containers =
    pharmavique.catalog
    pharmavique.ingestion
    pharmavique.search
    pharmavique.substitution
    pharmavique.recognition
    pharmavique.knowledge
    pharmavique.identity
    pharmavique.watchlist
    pharmavique.analytics
```

A `layers` contract alone still lets `presentation` import `infrastructure` (it is "above" it). C2 closes that gap.

### C2. Presentation and infrastructure are siblings, and presentation skips domain

```ini
[importlinter:contract:presentation-not-infrastructure]
name = Presentation must not import infrastructure or domain
type = forbidden
source_modules =
    pharmavique.catalog.presentation
    pharmavique.ingestion.presentation
    pharmavique.search.presentation
    pharmavique.substitution.presentation
    pharmavique.recognition.presentation
    pharmavique.knowledge.presentation
    pharmavique.identity.presentation
    pharmavique.watchlist.presentation
    pharmavique.analytics.presentation
forbidden_modules =
    pharmavique.catalog.infrastructure
    pharmavique.catalog.domain
    pharmavique.ingestion.infrastructure
    pharmavique.ingestion.domain
    pharmavique.search.infrastructure
    pharmavique.search.domain
    pharmavique.substitution.infrastructure
    pharmavique.substitution.domain
    pharmavique.recognition.infrastructure
    pharmavique.recognition.domain
    pharmavique.knowledge.infrastructure
    pharmavique.knowledge.domain
    pharmavique.identity.infrastructure
    pharmavique.identity.domain
    pharmavique.watchlist.infrastructure
    pharmavique.watchlist.domain
    pharmavique.analytics.infrastructure
    pharmavique.analytics.domain
```

(One generated contract per context may be cleaner than one large one; a small script can emit them, and CI checks the config is in sync with the folder list.)

### C3. Bounded contexts are independent, with an explicit allow-list

```ini
[importlinter:contract:context-independence]
name = Contexts do not import each other except through allow-listed contracts edges
type = independence
modules =
    pharmavique.catalog
    pharmavique.ingestion
    pharmavique.search
    pharmavique.substitution
    pharmavique.recognition
    pharmavique.knowledge
    pharmavique.identity
    pharmavique.watchlist
    pharmavique.analytics
ignore_imports =
    # ---- THE ALLOW-LIST: this block IS the context map. Adding a line = reviewed architecture change. ----
    # sync calls (outbound adapters in infrastructure)
    pharmavique.ingestion.infrastructure.adapters.catalog_writer -> pharmavique.catalog.contracts
    pharmavique.substitution.infrastructure.adapters.catalog_reader -> pharmavique.catalog.contracts
    pharmavique.recognition.infrastructure.adapters.search_gateway -> pharmavique.search.contracts
    pharmavique.recognition.infrastructure.adapters.catalog_reader -> pharmavique.catalog.contracts
    pharmavique.knowledge.infrastructure.adapters.catalog_reader -> pharmavique.catalog.contracts
    pharmavique.watchlist.infrastructure.adapters.catalog_reader -> pharmavique.catalog.contracts
    pharmavique.analytics.infrastructure.adapters.catalog_exporter -> pharmavique.catalog.contracts
    pharmavique.search.infrastructure.adapters.catalog_exporter -> pharmavique.catalog.contracts
    # integration events (inbound subscribers in presentation)
    pharmavique.search.presentation.events -> pharmavique.catalog.contracts
    pharmavique.watchlist.presentation.events -> pharmavique.catalog.contracts
    pharmavique.analytics.presentation.events -> pharmavique.catalog.contracts
```

Because only `*.contracts` targets are ignored, importing any other module of another context (domain, application, infrastructure, presentation) is still a violation. `domain` and `application` can never appear in this list.

### C4. Domain purity: no frameworks, no drivers

```ini
[importlinter:contract:domain-purity]
name = Domain and application are framework-free
type = forbidden
source_modules =
    pharmavique.catalog.domain
    pharmavique.catalog.application
    pharmavique.ingestion.domain
    pharmavique.ingestion.application
    pharmavique.search.domain
    pharmavique.search.application
    pharmavique.substitution.domain
    pharmavique.substitution.application
    pharmavique.recognition.domain
    pharmavique.recognition.application
    pharmavique.knowledge.domain
    pharmavique.knowledge.application
    pharmavique.identity.domain
    pharmavique.identity.application
    pharmavique.watchlist.domain
    pharmavique.watchlist.application
    pharmavique.analytics.domain
    pharmavique.analytics.application
    pharmavique.shared_kernel
forbidden_modules =
    sqlalchemy
    fastapi
    pydantic
    redis
    arq
    httpx
    alembic
    opentelemetry
    pharmavique.foundation
allow_indirect_imports = True
```

`pydantic` is banned in `application` as well as `domain` (DTOs are frozen dataclasses) **[Decision D-3]**. Easy to relax if you prefer pydantic DTOs there.

### C5. Contracts expose nothing internal

```ini
[importlinter:contract:contracts-are-public-language-only]
name = contracts import only shared_kernel
type = forbidden
source_modules =
    pharmavique.catalog.contracts
    pharmavique.ingestion.contracts
    pharmavique.search.contracts
    pharmavique.substitution.contracts
    pharmavique.recognition.contracts
    pharmavique.knowledge.contracts
    pharmavique.identity.contracts
    pharmavique.watchlist.contracts
    pharmavique.analytics.contracts
forbidden_modules =
    pharmavique.foundation
    pharmavique.bootstrap
    sqlalchemy
    fastapi
    pydantic
    # plus each context's own domain/application/infrastructure/presentation (generated per context)
```

### C6. Technical kernel stays below the contexts, composition root stays on top

```ini
[importlinter:contract:foundation-below-contexts]
name = shared_kernel and foundation know nothing about contexts or bootstrap
type = forbidden
source_modules =
    pharmavique.shared_kernel
    pharmavique.foundation
forbidden_modules =
    pharmavique.catalog
    pharmavique.ingestion
    pharmavique.search
    pharmavique.substitution
    pharmavique.recognition
    pharmavique.knowledge
    pharmavique.identity
    pharmavique.watchlist
    pharmavique.analytics
    pharmavique.bootstrap

[importlinter:contract:nothing-imports-bootstrap]
name = Only the process entrypoints import bootstrap
type = forbidden
source_modules =
    pharmavique.catalog
    pharmavique.ingestion
    pharmavique.search
    pharmavique.substitution
    pharmavique.recognition
    pharmavique.knowledge
    pharmavique.identity
    pharmavique.watchlist
    pharmavique.analytics
    pharmavique.shared_kernel
    pharmavique.foundation
forbidden_modules =
    pharmavique.bootstrap
```

### What each contract guarantees

| Rule from the brief | Enforced by |
|---|---|
| Dependencies point inward only | C1, C2 |
| Domain has no framework imports, no I/O | C4 |
| Modules can be extracted later | C3 (allow-list), C5 |
| Violation fails the build | CI runs `lint-imports`; non-zero exit blocks merge |

---

## 3. Architecture tests (rules import-linter cannot express)

Run in `tests/architecture/` as ordinary pytest tests:

1. No foreign key crosses a schema boundary; no SQL in one context references another context's schema.
2. Every table lives in its owning context's schema.
3. Every class in `*.contracts.events` is registered in the event registry with a `schema_version`.
4. Every context folder has the same four layers plus `contracts` (shape test).
5. The allow-list in C3 matches the actual adapter files (no dead entries, no unlisted adapters importing contracts).
6. Log-scrubbing test: sensitive field names never appear in rendered log records.

---

## 4. Things I need you to confirm before scaffolding

See `OPEN_QUESTIONS.md` section A, decisions D-1 to D-6: event ownership, inbound adapters in `presentation`, pydantic ban in `application`, presentation not importing `domain`, projections owning their data, and per-context migrations.
