# ADR-001: Modular monolith first, microservices only on measured need

| | |
|---|---|
| Status | **Accepted** (2026-11-16) |
| Date | 2026-11-16 |
| Deciders | Project owner, architecture lead |
| Related | [ARCHITECTURE.md](../ARCHITECTURE.md), [REPOSITORY_STRUCTURE.md](../REPOSITORY_STRUCTURE.md) |

## Context

The platform serves three user roles from one shared core and is split into nine bounded contexts (`catalog`, `ingestion`, `search`, `substitution`, `recognition`, `knowledge`, `identity`, `watchlist`, `analytics`). The brief requires Domain-Driven Design with Onion/Hexagonal layering, a modular monolith first, and a documented path to extracted services.

Forces at play:

- **Boundaries are not yet proven.** We are in Phase 0. Context boundaries (for example where change events are emitted, how product identity works across markets) will move as we learn from real SFDA data. Moving a boundary inside one codebase is a refactor; moving it between services is a migration project.
- **Strong transactional coupling in the core path.** `ingestion` applies batches to `catalog`, and `catalog` must emit change events atomically with its state change. Across a network this becomes distributed-consistency work before there is any product value.
- **Workload shape differs by area** (read-heavy lookups, bursty photo recognition, periodic bulk ingestion), which argues for separate *process roles and scaling*, not necessarily separate *services*.
- **Operational capacity is unknown.** Team size and ops experience are not stated (OPEN_QUESTIONS Q-1). Microservices multiply deployables, pipelines, observability surface and on-call load. This ADR assumes a small team and revisits if that is wrong.
- **Sensitive health data** and two jurisdictions raise the cost of every additional network hop and datastore that must be secured and audited.
- **Extraction must stay cheap.** The brief requires that any module can be extracted later.

## Options considered

### A. Microservices from day one
- Pros: independent scaling and deploys from the start; hard isolation of faults and data.
- Cons: distributed transactions and eventual consistency from the first sprint; contract and versioning overhead before contracts are stable; heavier local dev and CI; observability and security work multiplied by service count; boundary mistakes are expensive to fix.

### B. Modular monolith with machine-enforced boundaries (chosen)
- One deployable codebase and one PostgreSQL cluster; one schema per context; contexts communicate only through published `contracts` (sync) and integration events (outbox); import-linter fails the build on violations.
- Pros: one transaction per context without network cost; cheap refactoring while boundaries settle; simple local dev and CI; can already scale by process role (`api`, `worker`, `outbox-relay`) from the same image.
- Cons: single release unit and shared fate for the process; discipline needed to keep boundaries honest (mitigated by CI enforcement, not convention); one Postgres cluster is a shared bottleneck and failure domain.

### C. Conventional layered monolith without enforced boundaries
- Pros: least upfront work.
- Cons: boundaries erode, extraction later means a rewrite. Rejected: contradicts the brief's extraction requirement.

## Decision

Adopt **option B**. The system is a modular monolith whose boundaries are enforced as follows:

1. Each context is a top-level package with `domain`, `application`, `infrastructure`, `presentation` and a published `contracts` package.
2. Contexts talk through `contracts` only, from allow-listed adapter modules; data is owned per schema with no cross-schema foreign keys or joins.
3. State changes publish integration events through a transactional outbox; subscribers are idempotent.
4. import-linter contracts (see REPOSITORY_STRUCTURE.md) and architecture tests run in CI; a violation fails the build.
5. Scale by process role first (`api`, `worker`, `outbox-relay`), extract a context only on evidence (ARCHITECTURE.md section 7).

### Revisit triggers

This decision is revisited, and a context extracted by a new ADR, when measured data shows any of:

- A context's load profile forces a different scaling or hardware shape than the rest, and process-role scaling plus caching are exhausted (load tests, Phase 7, with targets agreed in Q-11).
- A context needs an isolated failure domain, release cadence or data store (for example prescription images, or a flaky external provider).
- Team structure makes a shared deployable the coordination bottleneck.

Targets for these triggers are not set yet; they depend on Q-1 and Q-11.

## Consequences

Positive:
- Fast iteration on boundaries and domain model during Phases 1 to 3.
- Atomic state-change-plus-event within a context, with no distributed transaction.
- A single container image and one CI pipeline.
- The extraction path is concrete and checkable (ARCHITECTURE.md 7.3).

Negative / risks:
- **Boundary erosion risk** if contracts are weakened. Mitigation: import-linter in CI, an allow-list that makes new cross-context edges a reviewed diff, architecture tests for schema isolation.
- **DTO translation overhead** between contexts (anti-corruption adapters). Accepted as the cost of extractability.
- **Shared database** is a single point of failure and contention. Mitigation: schema per context, read replicas and caching on the read path, backups and restore drills in Phase 7. Per-context databases are a post-extraction concern.
- **Monolith habits.** Reviewers must reject any shortcut that bypasses `contracts`, even when "it is just one import".

## Not decided here

The message broker for post-extraction events, the extraction order, and the specific patterns (CQRS-lite, outbox, repository/UoW, idempotent ingestion) beyond what is summarized in ARCHITECTURE.md section 6. Those get their own ADRs (ADR-004 to ADR-006, planned).
