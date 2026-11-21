# Performance: what was measured, and what scaling needs

Date: 2026-11-21. No target numbers were given or assumed (Q-11): these are **measured baselines** to
compare later runs against. Decisions behind them: [ADR-012](adr/ADR-012-shared-state-read-cache-and-jobs.md).

## How it was measured

`scripts/loadtest.py` (Python, httpx): each virtual user sends one request at a time and starts the
next at once. Scenarios: `search` (about 30 names, English, Arabic and half-typed), `page` (the drug
page of real register numbers), `mixed` (60% search, 40% page). 15 seconds per run, rate limits off.

Machine: the owner's laptop (Windows 11, 16 logical cores), PostgreSQL 17 and Redis 7 in Docker on the
same machine, 9,144 products loaded, **the load generator on the same machine** as the server, so
both compete for the CPU. The numbers understate what the server alone can do.

```powershell
uv run python scripts/loadtest.py --base-url http://127.0.0.1:8010 --scenario mixed --concurrency 50 --seconds 15
```

## Results (one `uvicorn` process unless stated)

| Run | Users | Requests per second | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|---|
| search, no cache | 10 | 124 | 69 | 99 | 157 |
| search, no cache | 50 | 118 | 342 | 502 | 2,475 |
| drug page, no cache | 10 | 297 | 32 | 42 | 56 |
| drug page, no cache | 50 | 266 | 127 | 233 | 2,195 |
| search, cache | 10 | 685 | 12 | 16 | 20 |
| drug page, cache | 10 | 988 | 9 | 11 | 26 |
| mixed, cache | 10 | 936 | 11 | 13 | 16 |
| mixed, cache | 50 | 366 | 73 | 458 | 768 |
| mixed, cache | 200 | 214 | 449 | 4,110 | 5,320 |
| mixed, cache, **4 worker processes** | 50 | 667 | 52 | 219 | 358 |
| mixed, cache, **4 worker processes** | 200 | 456 | 298 | 1,290 | 1,942 |

Every request in these runs answered 200 (no errors, no 429).

## What it shows

- The shared cache makes a lookup 5 to 8 times faster for a small crowd (search p50 69 ms to 12 ms,
  throughput 124 to 685 requests a second at 10 users).
- One process saturates at a few hundred requests a second here, and latency then grows with the
  crowd (users divided by throughput). The drop above 10 users is partly the load generator on the
  same CPU, so do not read it as the server's ceiling.
- Four worker processes lifted the mixed run from 366 to 667 (50 users) and 214 to 456 (200 users)
  requests a second: about 2x for 4x the processes, again limited by the generator on the same
  machine. This is what the stateless design allows: instances share the rate limit, the cache and
  the job queue through Redis.
- The maximum latencies of about 2 seconds at the start of a run are new database connections
  to `localhost` on Windows (the name resolves to IPv6 first). Use `127.0.0.1` in
  `PHARMAVIQUE_DATABASE_URL` and `PHARMAVIQUE_REDIS_URL` (the code already does this for Redis).

## Not measured yet

- The assistant and the scan, which need model keys and cost money per call; use the jobs endpoints
  and measure queue wait separately from model time.
- A real deployment: separate machines for the generator, the API, Postgres and Redis.
- Writes: the daily load and relay while users read.

## What a very large user base still needs (deployment work, not code)

1. Several API instances behind a load balancer (`PHARMAVIQUE_TRUSTED_PROXY_HOPS=1`), health checks on
   `/health`, autoscaling on CPU or latency.
2. PgBouncer in front of Postgres, a read replica for the read endpoints, and a managed Redis with
   failover.
3. A CDN in front of the API for the cached public answers (the responses already say
   `Cache-Control: public, max-age=60`) and for the product pictures (object storage, not the API's disk).
4. `pharmavique worker` processes for scans and assistant questions, with
   `PHARMAVIQUE_JOB_BACKEND=arq`; scale them by queue wait.
5. Per-account rate limits for signed-in users, and email through a provider queue (Wave I).
6. A load test from separate machines against that setup, with targets the owner sets.
