# ADR-004: Scalability strategy

| | |
|---|---|
| Status | **Proposed** (awaiting review) |
| Date | 2026-11-17 |
| Related | [ADR-001](ADR-001-modular-monolith-vs-microservices.md), [ADR-002](ADR-002-job-queue.md), [ADR-003](ADR-003-search-strategy.md), [ARCHITECTURE.md](../ARCHITECTURE.md), OPEN_QUESTIONS Q-11 |

## Context

The owner wants the system to be scalable. "Scalable" needs numbers, and we do not have them yet (Q-11: concurrent users, requests per second, photos per minute, latency targets). What we do know:

- **The catalog is small.** About 9,000 drugs per market. A full snapshot is about 18,000 detail pages, but the live catalog is a few thousand rows. It fits in memory. The scaling problem is **request volume and concurrency**, not data size.
- **Reads dominate** (lookups, equivalents, price pages) and are almost entirely cacheable.
- **AI features are the expensive part**: OCR of boxes, shelves and prescriptions, speech-to-text, LLM calls. They are slow, cost money per call, depend on outside providers and arrive in bursts.
- **Ingestion is periodic and heavy** but runs in the background and is rate-limited by the source, not by us.
- **Alerts fan out**: one price change can concern many users' lists and pharmacies' shelves.
- Health-related data (prescription photos, personal lists) raises the cost of every extra copy or hop.

## Decision

Scale in this order, adding each step only when measurements show it is needed.

1. **Stateless API processes.** Any number behind a load balancer; all state in Postgres, Redis and object storage. (Already the design.)
2. **Cache the read path.** Hot lookups in Redis with explicit invalidation when ingestion publishes changes. Because the catalog is small, a versioned in-process copy of the hot data is also an option. Keyset pagination for long lists.
3. **Postgres read replica** for the read path when one primary is no longer enough. Snapshot and history tables partitioned by date.
4. **Heavy and slow work is asynchronous.** OCR, STT, LLM and ingestion run as jobs (ADR-002): accept, queue, poll or webhook. The API never waits on a provider inside a request.
5. **Separate worker pools per workload** (vision/OCR, speech, LLM, ingestion), so a burst of photos cannot starve lookups or alerts.
6. **Back-pressure and limits at the edge**: per-user and per-tenant rate limits in Redis, admission control when queues are deep, explicit timeouts, **circuit breakers and fallbacks** (for example "provider slow, search by name instead"), and a **cost budget** per tenant for AI calls.
7. **Alerts through the outbox.** A change event is written with the state change, subscribers compute who is affected by product id (indexed), and notifications go through a queue in batches or digests.
8. **Multi-tenancy** with `tenant_id` and row-level isolation, plus per-tenant quotas, so one pharmacy or company cannot degrade others.
9. **Observability from the start**: traces that cross async hops, per-endpoint latency and error SLOs, queue depth and age, AI cost per request.
10. **Load tests with agreed targets** (k6 or Locust) before launch, and again before each extraction decision.

Extraction to services follows ADR-001: the first candidates are the AI/OCR workers, because their load profile differs most from the rest.

## Not doing now

Microservices, Kubernetes-specific design, a separate message broker, event sourcing, sharding. Each needs measured evidence first.

## Consequences

- Cheap to start: one deployable, the existing stack.
- AI cost and latency are controlled by design, not by hope.
- The numbers in Q-11 are required before choosing instance sizes or replica counts; until then these are structure decisions, not capacity claims.
- Extra moving parts appear only with evidence, and each has a written trigger.

## Revisit when

p95 latency of any read endpoint misses its target after caching; queue age for any AI workload exceeds its target; AI cost per active tenant exceeds its budget; or Postgres CPU or connections are the bottleneck after caching and a replica.
