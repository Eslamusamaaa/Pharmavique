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

## Production on Vercel, and the assistant (2026-11-25)

The owner uses `https://pharmavique.vercel.app` (Vercel Hobby, fra1; Neon in Frankfurt; no Redis), so
this round was measured there, from Egypt, with `curl` (TLS to fra1 is about 0.13 s of every request).

### What was slow

| What | Measured | Cause |
|---|---|---|
| First request to a fresh instance | 8.2 s (`/health`) | the function bundle was 327 MB, over Vercel's 250 MB standard size ("optimizing dependencies" in the build log), because `playwright` (about 117 MB with its driver) was a runtime dependency; then about 5 s of Python startup: 3.0 s of imports (LangChain, LangGraph and the OpenAI client 1.7 s of it) and 2.2 s of creating twelve HTTP clients that each loaded the certificate bundle (0.18 s each) |
| Other requests to a fresh instance | 1 to 3.3 s (shortage, similar names, same ingredient) | the same cold start; these answers were not cached anywhere |
| Warm requests | 0.21 to 0.32 s | fine: about 0.13 s of it is the connection |
| Edge cache | 60 s | `Cache-Control: max-age=60` only |
| Opening the app | a function call every time | the page shell was `no-store`, so it could wait for a cold start before anything showed |
| Web scripts | 7.3 MB (1.4 MB compressed; Vercel compresses with brotli) | every one of the 9,263 phosphor icons was bundled: 3.3 MB of the 6 MB `__common` file |
| Assistant | 29 s and 65 s on two of three questions; 4.8 s on the third | Groq's free plan allows 8,000 tokens a minute per model and one question takes 10,000 to 16,000 (every call repeats the 2,800-token prompt and all tool results), so the second or third call is refused and the question moves to Gemma on Cloudflare, which thought for 5 to 29 s a call. Six document passages made one call 12,500 tokens, which Groq refuses outright |

### What changed

- `playwright` is the optional `scraper` extra (`uv sync --all-extras`; the crawl workflows install it).
- The language-model stack is imported on the first question, and the HTTP clients share one TLS
  context. Local startup: about 5.2 s to 1.2 s. A test keeps those libraries out of the API's startup.
- Public answers carry `s-maxage=600, stale-while-revalidate=86400`, and same-ingredient, shortage,
  similar names, contraindications and compare go through the read cache too. The no-picture 404 is
  kept for a day. The page shell is `max-age=0, must-revalidate, s-maxage=3600` (Vercel clears its
  edge cache with every deployment).
- Icons are imported one by one (`mobile/src/components/icons.ts`): web scripts 7.3 MB to 1.8 MB
  (490 KB compressed).
- Assistant: Groq's `gpt-oss-20b` (its own 8,000 tokens a minute) comes right after `gpt-oss-120b`;
  Gemma runs with thinking off (a three-sentence answer 11.7 s to 2.5 s); tool results go to the model
  as compact JSON, documents as four passages of 800 characters; the backup timeout is 25 s.

### Assistant after the change (same six questions in a row, local API, real providers)

| Question | Before | After |
|---|---|---|
| بديل أرخص لبنادول اكسترا | 29.1 s | 4.5 s |
| what is augmentin 1g used for | 64.8 s | 8.2 s |
| نقص اوزمبيك | 4.8 s | 11.3 s (Gemma, five calls) |
| سعر كونكور 5 | (not run) | 4.3 s |
| تداخل بروفين واسبرين | (not run) | 5.7 s |
| بديل نيكسيوم 40 | (not run) | 9.5 s |

All six answered with citations. Groq still runs out within a minute when questions follow each
other; then Gemma answers in 1 to 8 s a call. A provider with a larger free token limit would remove
most of the remaining wait (not set up: it needs a new key from the owner).

### Production after the deployment (2026-11-25, deployment `pharmavique-qj2bn3so4`)

The build log no longer says "exceeds the standard size"; `__common` is 394 KB (was 6 MB).

| What | Before | After |
|---|---|---|
| First request to the new deployment (`/health`) | 8.2 s | 0.45 s |
| First request after 15 minutes without traffic (a real cold start) | 8.2 s | 3.2 s (the next ones 0.29 to 0.49 s) |
| First search on it | 2.0 s | 1.8 s (then 0.27 s) |
| Eight simultaneous uncached searches | not measured | 0.50 to 0.63 s each |
| Drug page requests, first time | 0.27 to 3.3 s | 0.43 to 0.75 s; similar names 3.1 s |
| The same requests again | 0.21 to 0.32 s (function) | 0.21 to 0.23 s, `X-Vercel-Cache: HIT` |
| App shell | a function call | `HIT` at the edge, 0.22 s |
| Assistant (four questions, one at a time) | 29 to 65 s when Groq ran out | 4.5 to 7.6 s, all cited |

Still slow after that deployment: the first similar-names answer of each instance (3.1 s) read all
9,186 products in full to build the name index. It now reads only the register number and the two
trade names (`CatalogNames.trade_names`: 0.04 s locally) and reduces each distinct brand once (about
45% of the names repeat). Building the index locally: 1.7 s to 0.5 s, with the same matches on 300
random products. Then (same day) the daily refresh stores every product's look-alikes in
`search.similar_name` (126 s for 9,186 products locally) and the API reads one row: 0.05 s for the first
answer locally, the same answers as the index on 200 of 200 sampled products (rate limit and shared cache
off while comparing). In production (filled 2026-11-25, 1 minute on GitHub): 0.27 to 0.30 s for drugs never
asked before, no fallback in the logs; the first request after 40 idle minutes took 3.3 s, the cold start.

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
