# Audit and improvement plan (2026-11-26)

Source: the master audit prompt pasted on 2026-11-26. This file records the first verification pass
(read-only, against the code at `be573cd`) and the proposed order of work. Nothing is implemented
yet; the owner approves the scope and answers the questions at the end first (CLAUDE.md: plan,
then wait for approval).

Status words: CONFIRMED, INCORRECT, ALREADY FIXED, PARTIAL, NEEDS INVESTIGATION.
"Verified in code" means read in the source; nothing below was run against Neon or a real crawl.

## 1. Findings verified so far

| # | Finding | Status | Evidence |
|---|---|---|---|
| A1 | Nightly backup covers only catalog, search, interactions; 2-day retention | CONFIRMED | `.github/workflows/daily-refresh.yml:86-105` |
| A1 | Identity, assistant, watchlist, knowledge not backed up anywhere | CONFIRMED | same; `db-migrate.yml` dumps only `catalog` |
| A1 | `db_snapshot.sh` commits dumps to `data/db` | CONFIRMED, but only public schemas (catalog, search, knowledge, interactions); git history has no identity/assistant/watchlist dumps | `scripts/db_snapshot.sh:16`, `git log --all -- data/db/identity*` empty |
| A1 | Pre-migration dump | PARTIAL: catalog only | `db-migrate.yml` |
| A2 | `FallbackVisionReader` accepts `[]` from garbage output; no per-reader or overall deadline | CONFIRMED | `recognition/infrastructure/openai_vision.py:80-104,158-175` |
| A3 | Rate limit in-memory per instance | PARTIAL: uses the shared KV store when present, falls back per instance; production has no Redis, so per instance in practice | `bootstrap/rate_limit.py:1-8` |
| A3 | No per-account login throttle / lockout | CONFIRMED (only emailed codes have 5 attempts) | `identity/domain/user.py:21` |
| A3 | `trusted_proxy_hops` default 0 | CONFIRMED in code; Vercel env value NEEDS INVESTIGATION (owner) | `bootstrap/settings.py:43` |
| A3 | `login_for_ai` on | CONFIRMED default `True`; Vercel override NEEDS INVESTIGATION | `bootstrap/features.py:28` |
| A3 | Inline jobs via `asyncio.ensure_future` | CONFIRMED | `foundation/jobs.py:169`, `bootstrap/api_assistant.py:203` |
| A4 | No app-level encryption of chat text | CONFIRMED (no encrypt/pgcrypto in src) | grep |
| A4 | Share ids unguessable, opt-in | CONFIRMED OK: `secrets.token_urlsafe(16)`, explicit share call, `unshare` exists | `assistant/application/history.py:242-256` |
| A9 | SECURITY.md says the API has no sign-in | CONFIRMED stale | `SECURITY.md:31` |
| A7 | No Postgres/Redis in CI, no coverage floor, mobile has no tests | CONFIRMED (CI runs `-m "not integration"`; no `fail_under`; 0 mobile test files) | `ci.yml:40`, `pyproject.toml:151` |
| B1.1 | Missing label becomes `None` silently | PARTIAL: mapping records issues for unreadable values, but a missing label (price, strength) gives `None` with no issue | `ingestion/.../sfda_web/mapping.py:173-235` |
| B1.1 | `Product.apply` overwrites non-null with null and emits `PriceChanged` to `None` | CONFIRMED | `catalog/domain/product.py:103-133` |
| B1.2 | Knowledge is additive only; edited/removed documents stay cited | CONFIRMED | `knowledge/application/new_rows.py`, `daily_refresh.sh:206-221` |
| B1.4 | 429 stops at once, `Retry-After` ignored | CONFIRMED (deliberate politeness rule; adding `Retry-After` must keep it polite) | `polite_fetch.py` |
| B1.3 | Retry backoff is linear, exit codes coarse | CONFIRMED linear (`retry_wait * attempt`); exit-code detail NEEDS INVESTIGATION | `polite_fetch.py:45-66` |
| A6 | Linux has no OCR for scanned PDFs | CONFIRMED | `daily_refresh.sh:219` |
| B2.7 | get()+save() per product | CONFIRMED | `catalog/application/handlers.py:41-48` |
| B2.9 | No HNSW index | CONFIRMED in code (migration says "the embedding job creates it", no code does); local/Neon DB NEEDS INVESTIGATION | `knowledge/.../0001_create_knowledge_schema.py:10` |
| B2.9 | `OR ... ILIKE` bypasses trigram index | CONFIRMED shape; needs EXPLAIN | `knowledge/infrastructure/postgres.py:124` |
| B2.11 | `s-maxage=600`, `stale-while-revalidate` long | CONFIRMED | `bootstrap/cached_response.py:21-45` |
| B2.13 | Pool 10 + overflow 20 = up to 30 per instance (worse than reported 20) | CONFIRMED | `bootstrap/settings.py:48-49` |
| B2.14 | 17 files with ScrollView, 1 with a list | CONFIRMED count; which are long lists NEEDS INVESTIGATION | grep in `mobile/` |
| — | 177 Python test files (prompt said 181) | noted | `find tests` |

### Part C (assistant) — what exists today

- Emergency regex before any model call (overdose, breathing, swelling, fainting, seizure,
  suicide) -> fixed 997 reply. **No headache red flags** (thunderclap, neuro deficit, fever + stiff
  neck, vision): CONFIRMED gap. `assistant/domain/answers.py:72-92`
- Post-model guards: dose/stop/switch sentences removed, numbers not returned by a tool removed,
  "used for" claims removed when no document/web was retrieved. `assistant/application/ask.py`
- Interactions: prompt already says "no record is never a safety verdict"; a `coverage` record kind
  exists. Whether the three states (documented / none found / not covered) reach the answer in
  code, not only in the prompt: NEEDS INVESTIGATION.
- Contraindications tool exists (MeDIC + US labels).
- **No intent classification and no structured decision layer**: one LangGraph agent decides
  everything from the prompt. The prompt explicitly allows "which ingredients are generally used
  for these symptoms" with no red-flag or context step first -> explains the migraine failure
  (Test 1/5). CONFIRMED root cause.
- No medical regression suite with the six mandatory conversations: CONFIRMED missing.

## 2. Proposed order (one small commit per item, five checks green each time)

**Batch 1: P0 safety and data integrity (code only, no production touch)**
1. C: rule-based intent classifier (info / symptom-treatment / drug-specific / interaction /
   emergency) in `assistant/domain`, pure and tested; feature flag `PHARMAVIQUE_FEATURE_TRIAGE`.
2. C: headache/migraine and general red-flag rules in `assistant/domain`; urgent reply before the
   model. Tests from Test 1 and Test 5.
3. C: symptom-treatment path: when intent is symptom-treatment and key context is missing (age,
   pregnancy, other medicines, conditions, red flags), the assistant asks one short structured
   question set alongside the general categories. Products may be named (owner's decision, §3),
   prescription-only ones marked as such from the registry's legal status field (to confirm it
   exists in our data first), always with the "consult a doctor first" warning added in code.
4. C: interaction result states as code (documented / none found in sources / not covered), with a
   post-check that rejects "safe"/"no interaction" wording when the state is not "documented
   none". Test 3.
5. C: medical regression suite `tests/eval/medical/` with the six conversations as deterministic
   tests over a fake model + the decision layer (structure checks: intent, red flags asked,
   no prescription push, citation kinds), plus an opt-in live run script reporting real outputs.
6. B1.1: `Product.apply` never replaces a non-null field with null; missing required labels become
   issues; run fails above a threshold of records missing Register/Trade/Scientific/Price;
   schema fingerprint per run. Golden-file test from a saved real page in `data/`.
7. A2: vision fallback treats unparseable output as failure, per-reader timeout 20 s, overall
   deadline below `job_timeout_seconds`.

**Batch 1 status (2026-11-26, local only, not pushed):**

| Item | State | Commits |
|---|---|---|
| 1–3 triage, red flags, treatment path, dialect | done (ADR-024, flag `PHARMAVIQUE_FEATURE_TRIAGE`) | b558f70, 15d4b7f |
| 4 interaction states | partly: no-clearance filter and model instruction; the three states are not yet passed from `check_interactions` as data | b558f70 |
| 5 regression suite | deterministic part done (fake model); live run over real models not built | bd85524 |
| 6 catalog integrity | known values kept; load refused (exit 5) above 2% missing required labels, measured on the real full crawl (9,145 drugs, 1 missing scientific name). Fingerprint compare with the last run and golden page test moved to Batch 3 | 8e632f5, 07280cd |
| 7 vision fallback | done: invalid output fails over, 20 s per model, 60 s per scan | 13823dc |

Checks at 07280cd: ruff, ruff format, mypy (562 files), lint-imports (8 kept), pytest 1,966
passed / 22 skipped (unit; integration not run).

**Batch 2: P0 infrastructure (needs owner answers below)**
8. A1: one nightly backup job for all schemas, encrypted with `age` (public key in repo, private
   key only with the owner), uploaded to private storage, 30-day retention; full pre-migration dump
   in `db-migrate.yml`. Restore drill into a fresh Neon branch via Actions, counts only in logs.
   RUNBOOK update with tested steps and the per-scenario loss table.
9. A3: per-account login throttle stored in Postgres (no new service); shared rate limit in
   Postgres or Upstash (owner's choice); cap inline jobs and document it.
10. A9: SECURITY.md rewritten to match the real sign-in.

**Batch 3: crawler correctness (B1.2–B1.6)**: content hashes for knowledge rows, re-chunk only
changed rows, mark removed documents inactive and exclude from retrieval; `Retry-After` honoured
(wait, never hammer), exponential backoff with jitter, distinct exit codes; freshness in `/ready`
(36 h); a second scheduled attempt.

**Batch 4: P1 and performance (measure before/after with EXPLAIN ANALYZE on the local DB)**:
HNSW index, BY_TEXT rewrite, bulk catalog load, incremental search reindex, `ingredient_key` +
GIN, pool size for serverless, cache times per data kind, model health check workflow, CI
Postgres/Redis service + migrations up/down + coverage floor.

**Batch 5: P2 and the rest**: JWT `kid` rotation, mobile list screens, scan eval tuning,
chat-text encryption, Linux OCR, clinical source ingestion (C4) and citation-claim checks (C5).

Not attempted without explicit approval: any write to production Neon, the restore drill, new
paid services, new external data sources.

## 3. Owner's decisions (2026-11-26)

These override the pasted prompt where they conflict.

| Topic | Decision | Effect on the plan |
|---|---|---|
| Assistant dialect | Match the user: Egyptian when the user writes Egyptian, Saudi otherwise; English medical terms kept | Prompt + dialect detection in item 3; fixed strings stay Saudi |
| Alerts | Email through our own SMTP when the refresh fails or data is older than ~36 h | Replaces "GitHub failure emails only"; Batch 3 freshness check sends it |
| Backups | Second Neon account (owner creates it): nightly full restore into a project there (also a daily restore drill) + encrypted dumps kept 30 days in its Object storage | Item 8; free Object storage size to be checked in Neon docs first |
| Restore drill | Approved: a workflow that only reads production and restores elsewhere, counts only in logs; shown to the owner before it runs | Item 8 |
| Shared rate limit / lockout | Upstash Redis free if it needs no card (owner tries); Postgres otherwise | Item 9 waits on the account |
| Clinical sources (C4) | All at the very end | Batch 5 |
| Symptom questions | Red flags first, explain the categories, ask about pregnancy / conditions / other medicines, and name products (prescription-only included), each time with a "consult a doctor before taking any medicine" warning | Item 3 changes: no ban on naming products; the warning is enforced in code; no-dose and no stop/switch guards stay |
| `trusted_proxy_hops`, `login_for_ai` on Vercel | Owner checks and reports | Item 9 |
