# ADR-002: Job queue: Arq (behind a port) over Celery

| | |
|---|---|
| Status | **Accepted** (2026-11-16; owner said to keep the recommendation, Arq behind a port, knowing it is maintenance-only) |
| Date | 2026-11-16 |
| Deciders | Project owner, architecture lead |
| Related | [ARCHITECTURE.md](../ARCHITECTURE.md), OPEN_QUESTIONS Q-10, Q-11 |

## Context

Background work in this system:

| Work | Profile | Why it cannot run in the request cycle |
|---|---|---|
| Photo recognition | Bursty, I/O-bound (calls an external vision provider), needs status endpoint, per-user rate limits, back-pressure, timeout/fallback | Provider latency is unpredictable; bursts must not starve lookups |
| Bulk ingestion (SA API/file, EG CSV) | Long-running, batch upserts, must be idempotent and resumable | Minutes-long, heavy writes |
| Knowledge indexing (Phase 4) | Chunking and embedding calls | Throughput-bound, external provider |
| Scheduled work | Periodic source pulls, reconcilers | Time-triggered |

The brief asks to pick Arq or Celery and justify. The outbox relay is *not* a queue job: it is a dedicated polling process (ARCHITECTURE.md 4.4).

Constraints that shape the choice:

- The codebase is async end to end (FastAPI, SQLAlchemy 2 async). Jobs reuse the same async application handlers.
- Redis is already in the stack (cache, rate limiting).
- Job *truth* will live in Postgres (`recognition` job rows, `ingestion` runs with checkpoints), so a lost or duplicated queue message must be recoverable. The queue is a wake-up mechanism, not the system of record.
- Delivery is at-least-once, so every job handler is idempotent regardless of the library.

## Options considered

### A. Arq
- Native `asyncio`: jobs are `async def` and call application handlers directly, sharing the async SQLAlchemy and HTTP client patterns used by the API.
- Redis only (no new infrastructure). Provides retries, per-job timeouts, deferred jobs, cron schedules and job-id based de-duplication.
- Small and simple; low operational surface.
- **Risk: the project is in maintenance-only mode** (stated in its README and on PyPI; details are in the project's issue tracker). No new features should be expected, and long-term compatibility with future Python and redis-py releases is not guaranteed by an active roadmap.
- Fewer built-in features: no rich workflow primitives, simple queue prioritisation (separate queues/workers), basic monitoring.
- Durability depends on Redis persistence and availability configuration.

### B. Celery
- Very mature and widely operated; rich features (routing, rate limits per task, canvas workflows, mature monitoring tooling), Redis or RabbitMQ brokers.
- Actively maintained.
- **Sync-first execution model**: the worker pool is process/thread based. Running our async handlers requires bridging into an event loop per task or per process, which complicates connection-pool lifecycle (SQLAlchemy async engines, HTTP clients) and is a known source of subtle bugs. (First-class async task support should be re-verified against the current Celery release before final sign-off; I have not confirmed its current state.)
- Heavier to configure and operate for the small set of features we need.

### C. Others (not selected; brief limits the choice to Arq or Celery)
Postgres-backed queues, Dramatiq, Taskiq, RQ and similar exist. I did not evaluate them in depth; they can be proposed by a new ADR if neither option holds up. A Postgres-backed queue would be attractive for transactional enqueue, and is the most plausible fallback.

## Decision

Use **Arq**, strictly behind a `JobQueue` port in `shared_kernel` with the adapter in `foundation.queue`, and keep **job state authoritative in Postgres**:

1. **Port first.** Application code depends only on `JobQueue` (`enqueue(job_name, payload, dedupe_key, defer_by, timeout)`), never on Arq types. A different backend is one new adapter plus a worker entrypoint.
2. **Postgres is the system of record.** A recognition job is a row (`queued`, `processing`, `succeeded`, `failed`, `timed_out`) created in the same transaction as the request; an ingestion run is a row with batch checkpoints. The queue message only says "go look at row X".
3. **Reconciler.** A scheduled job re-enqueues rows stuck in `queued`/`processing` beyond their timeout, so a Redis loss never loses work.
4. **Idempotent handlers.** Job id and `dedupe_key` derive from the business key (for example upload id, or source + snapshot content hash). Re-delivery is harmless.
5. **Back-pressure and limits at the edge.** Enqueue-side admission control (reject or defer when queue depth passes a threshold), per-user rate limits in Redis, explicit job timeouts, and a fallback result when the vision provider times out (status `timed_out` with a "try again or search manually" response).
6. **Separate worker pools** for `recognition` (many concurrent I/O jobs) and `ingestion` (few, long jobs) so bursts of one cannot starve the other.
7. **Production requirement:** Redis must be configured with persistence and high availability appropriate to the hosting choice (Q-1). This is a deployment prerequisite, not an application concern, thanks to points 2 and 3.

### Exit criteria (switch to Celery or another backend by a new ADR)

- A security or compatibility problem in Arq or its dependencies goes unfixed against a supported Python/redis-py version.
- We need features Arq lacks and cannot cheaply build (workflow chains, per-task rate limits, priorities).
- Load tests (targets pending, Q-11) show the worker pool model cannot meet recognition throughput.

Because of the port and Postgres-authoritative state, exit cost is deliberately small.

## Consequences

Positive:
- Async-native jobs share code paths with the API; fewer concurrency bugs and less boilerplate.
- No new infrastructure beyond Redis.
- Queue loss or duplication is a recoverable event, not a data-loss event.
- Backend can be replaced without touching use cases.

Negative / risks:
- **Arq's maintenance-only status** is a real long-term risk for a long-lived health product. Accepted because the feature set we need is small and the port plus exit criteria bound the risk. If you consider this unacceptable, the alternative is Celery with an explicit async bridge, at higher day-to-day complexity.
- We must build the reconciler, admission control and monitoring ourselves.
- Redis durability and HA become deployment requirements.

## Verification already done

I confirmed through a web search that Arq's README and PyPI listing state maintenance-only mode, and that the latest release found was 0.28.0. I did not review the linked issue for what "maintenance-only" promises in practice (for example security fixes); that should be read before sign-off.
