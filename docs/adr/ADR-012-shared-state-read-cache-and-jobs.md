# ADR-012: shared state, the read cache and background jobs

Status: accepted, 2026-11-21 (owner: "build for a very large number of users", Q-11).

## Context

Until now nothing used Redis: the rate limit and the spoken-answer links lived in each API process's
memory, search and drug pages hit Postgres on every request, and a photo scan held a connection for
6 to 40 seconds. That works for one process and fails behind several: each instance counts its own
requests, an audio link made on one instance 404s on another, and a burst of scans has no brake.

## Decision

- **One small shared store** (`foundation/kv.py`: `get`, `set`, `getdel`, `delete`, `bump`,
  `window_hit`) with a Redis adapter and an in-memory twin for tests. Every method works or raises
  `StoreUnavailable`; callers degrade and never fail the request because Redis is down.
- **Rate limit** counts in the store (a fixed one-minute window per caller, one round trip), so the
  limit holds across instances. If the store is down each instance counts for itself. Behind a load
  balancer the caller is the entry our balancer appended to `X-Forwarded-For`
  (`PHARMAVIQUE_TRUSTED_PROXY_HOPS`), never an entry the client could forge.
- **Read cache** (`foundation/read_cache.py`) for the answers that are the same for everyone: search
  and the product and drug pages. Keys carry a **data version**; anything that changes the answers
  bumps it (a relayed catalog event, `pharmavique cache-invalidate`, which the daily refresh runs
  after the drug and list loads), so old entries are never read again and expire on their own (10
  minutes, jittered). One computation per key at a time per process (no stampede). Only successful
  answers are stored (never a 404). Responses carry `Cache-Control: public, max-age=60` so browsers
  and a CDN take repeat traffic off the API, and `X-Cache: hit|miss` for measurement.
- **Spoken-answer links** move to the store (`SharedAudioStore`), with a per-process fallback.
- **Background jobs** (`foundation/jobs.py`, `arq_jobs.py`) for scans and assistant questions:
  `POST /v1/jobs/scan` and `/v1/jobs/assistant` answer 202 with a job id; `GET /v1/jobs/{id}` says
  queued, running, done (the same JSON the synchronous endpoint returns) or failed (a short code).
  The input (a photo) is stored under a short expiry and **deleted the moment a worker takes it**;
  state and result expire after 15 minutes; failures store a code, never text from the photo or the
  question. A job nobody picks up in 3 minutes reads as `worker_unavailable`. Arq moves the job id
  to `pharmavique worker` processes (max concurrency and a timeout per job, no retries: a scan costs a
  model call). With `PHARMAVIQUE_JOB_BACKEND=inline` (the default) the same jobs run inside the API
  process, so nothing extra has to be started. Per-caller submission limit and a queue-depth ceiling
  (503 with `Retry-After`) turn a burst into a short wait.
- The synchronous scan and assistant endpoints stay as the fallback.
- **Database pool** size is configurable (`PHARMAVIQUE_DB_POOL_SIZE`, `PHARMAVIQUE_DB_MAX_OVERFLOW`);
  with many instances put PgBouncer in front of Postgres.
- An empty environment variable now means "not set" (an empty `PHARMAVIQUE_REDIS_URL` used to crash
  the start).

## Consequences

- A catalog change reaches users within the data-version check (2 seconds) plus the browser's
  `max-age` (60 seconds), at worst; one price change invalidates every cached page, which is fine at
  the daily rhythm of the data and would need per-product versions if updates became continuous.
- Redis is now a dependency for the shared behaviour, but not for correctness: without it the API
  runs as before, per process.
- Measured numbers are in `docs/PERFORMANCE.md`. They come from one laptop and say what changed,
  not how much capacity a deployment has.
- Not done: Redis high availability (Sentinel or a managed service), read replicas of Postgres,
  a CDN in front of the API, per-account (not per-address) rate limits, and moving pictures to object
  storage. They are deployment work, listed in `docs/PERFORMANCE.md`.
