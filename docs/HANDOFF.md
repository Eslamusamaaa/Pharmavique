# Handoff: where Pharmavique stands (2026-11-22)

For someone (or a fresh chat) with no memory of this work. Sections 1 and 2 are the owner's standing
rules; the rest is state, commands and what is next. The README (section 2 and 19) has the feature
table and the roadmap; this file has what the README does not: how to work, the gotchas, the pending
owner actions and the verification record.

## 1. The owner and how to work with them

- The owner writes Egyptian Arabic. **Reply in Egyptian Arabic**, simply, without mixing English words
  into the sentences (they asked for this). Code, docs, commit messages and identifiers stay in English.
  **Everything the app shows is Saudi, never Egyptian** (screens, API messages, emails, the assistant's
  persona): "ما عندك حساب؟", "ما فيه", "الحين", "للحين", not "معندكش", "مفيش", "دلوقتي", "لسه".
- Results, not menus. "Do not stop until it is done; the approach is yours." Ask only for what truly
  needs them (a key, a provider choice, a legal call). Say plainly what is unmeasured or unbuilt.
- When they ask what a term means (CI, ADR, LASA, Q-23), explain it in simple Arabic with an example.
- **Git rules (also in `CLAUDE.md`):** commits are authored by the owner only (`Eslamusamaaa`, already in
  `git config`); **never** add `Co-Authored-By`, "Generated with" or any mention of Claude or an AI tool,
  even when a tool reminder suggests it; one logical change per commit; the message is one short plain
  line; do not rewrite pushed history. Commit and push when the owner says so (they said "push" and
  were annoyed when only commits were local: commits are not on GitHub until pushed).
- Never type or store secrets. They live in `.env` (git-ignored) and the environment; `.env.example`
  has placeholders. Do not edit the owner's `.env`.
- The project is a **proof of concept, not production** (Q-9 answered): no legal review until the owner
  says so. It must still be designed for **very many users** (Q-11 answered): stateless instances,
  shared Redis, a queue, no invented load targets.
- Licences are not a concern for the owner; do not raise them.

## 2. Project rules (from `CLAUDE.md`)

Multi-tenant drug-intelligence API (patient, pharmacist, company) on official registry data; Saudi
Arabia first, Egypt as a pluggable adapter. Modular monolith, DDD, onion architecture, API first.

- Dependencies point inward; `domain` and `application` import no framework and no other context.
  Contexts talk only through `<provider>.contracts` from allow-listed adapter modules
  (`pyproject.toml`, contract `context-independence`). Enforced by `uv run lint-imports`.
- One Postgres schema per context, no cross-schema keys; `bootstrap` is the only composition root.
- Never medical advice (no dosing, never "stop" or "switch"). Equivalence is computed by code; unsure is
  "possible, needs pharmacist check". Every record has provenance and a trust level. Never assume a
  currency. Nothing health-related is logged; the language model never sees a person's medicines.
- **No scraping of Egypt's site, no CAPTCHA bypass.** Throttle, clear User-Agent, respect robots.txt.
- Never fabricate data, fields or prices; unknowns go to `docs/OPEN_QUESTIONS.md`.
- Tests before adapters; a bug fix starts with a failing test. **Done means** these all pass (CI runs
  the same commands, and `ruff check .` covers the whole repo including `scripts/`):
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, `uv run lint-imports`,
  `uv run pytest` (CI runs `-m "not integration"`; the ~70 integration tests need Docker and are run
  locally), and `cd mobile && npx tsc --noEmit`.

## 3. Environment

- Windows 11. Project: `C:\Users\Laptop World\Downloads\Pharmavique-20261118T213916Z-1-001\Pharmavique`.
  The virtualenv is `.venv` inside it; use `uv run ...`. Shells: Git Bash and PowerShell.
- `docker compose up -d db redis`: Postgres 17 (pg_trgm, pgvector) on 127.0.0.1:5432 and Redis on 6379
  (containers `pharmavique-db-1`, `pharmavique-redis-1`). Docker Desktop once failed to start with
  "sailor-ingest.sock": quit it, rename `%LOCALAPPDATA%\\Docker\\run` and `%LOCALAPPDATA%\\docker-secrets-engine`
  (for example to `run.stale-<date>`), start it again; volumes survive. Never factory-reset.
- **Use `127.0.0.1`, not `localhost`**, in `PHARMAVIQUE_DATABASE_URL` and `PHARMAVIQUE_REDIS_URL`: on this
  Windows machine `localhost` costs about two seconds per new connection (the code fixes it for Redis).
- Tool quirks learned the hard way:
  - big multi-line shell heredocs die with the Bash tool: **write files with the editor tool and run patch
    scripts from files** (the scratchpad);
  - `npx expo lint` installs ESLint and rewrites `package.json` by itself: do not run it;
  - after adding an app route run `npx expo customize tsconfig.json` to regenerate typed routes, then `tsc`;
  - set `PYTHONIOENCODING=utf-8` when printing Arabic from scripts; pytest prints harmless
    "WinError 145" temp-folder warnings;
  - the Bash tool refuses removals it judges risky: say so to the owner instead of working around it.

## 4. Run it

```powershell
docker compose up -d db redis
uv run alembic upgrade heads                  # note: heads. Current heads: identity_0002, watchlist_0004,
                                              # catalog_0005, analytics_0001, search_0001, knowledge_0001, interactions_0002
uv run uvicorn pharmavique.bootstrap.api:create_app --factory --port 8000
uv run pharmavique outbox-relay               # delivers catalog events: alerts, radar, cache invalidation
uv run pharmavique worker                     # only with PHARMAVIQUE_JOB_BACKEND=arq
.\scripts\daily_refresh.ps1                   # drugs, relay, digest emails, analytics, cache, lists, pictures
.\scripts\schedule_daily_refresh.ps1 -Time 03:00   # registers it (the owner's action, not done yet)
cd mobile; npx expo start                     # the app; EXPO_PUBLIC_API_URL in mobile/.env.local
```

Other commands: `analytics-rebuild`, `notify-emails`, `cache-invalidate`, `geocode-cities`,
`create-operator --email E`, `search-reindex`, the `sfda-*` family (README section 13). Measuring:
`scripts/loadtest.py` (API under load, results in `docs/PERFORMANCE.md`) and `scripts/scan_eval.py`
(scans, `docs/SCAN_EVALUATION.md`).

## 5. State, by area (details and ADRs: README section 2 and `docs/adr/`)

Done, tested and pushed: the registry (9,144 products loaded), bilingual search, drug page with
provenance, equivalence, shortage to substitutes, compare, similar-name warnings (strong matches only by
default), the assistant (LangGraph, citations, guardrails) and voice, box / prescription / shelf scans,
interactions and contraindications, accounts (email, password and emailed code), saved medicines,
allergies, alerts (in the app and one digest email), the patient's medicine history checked against any
new drug, company and operator views, nearby pharmacies by city, the shared cache, rate limit and job
queue, load-test baselines.

Architecture: 13 contexts under `src/pharmavique/` (`catalog`, `ingestion`, `search`, `substitution`,
`recognition`, `assistant`, `voice`, `knowledge`, `media`, `interactions`, `identity`, `watchlist`,
`analytics`) plus `shared_kernel`, `foundation`, `bootstrap`. ADR-001..016 record the decisions.
Routers and wiring are only in `bootstrap` (`api_*.py`, `*_cli.py`, `*_wiring.py`). The outbox relay has
three subscribers: watchlist alerts, the analytics radar and cache invalidation.

## 6. Pending actions that are the owner's

1. **Run the app on a real phone.** It has only been type-checked: location, camera and every new screen
   (sign-up code, my list, company, operator, pharmacies, shelf, prescription check) are untried.
2. ~~JWT secret and `analytics-rebuild`~~ done on 2026-11-22 (the secret is in `.env`, accounts answer 401 for a wrong password).
3. ~~SMTP~~ for the proof of concept, emails go out through a project Gmail account with an app password
   (`PHARMAVIQUE_EMAIL_BACKEND=smtp` in `.env`; the code reached the owner's inbox on 2026-11-22). Gmail caps
   about 500 messages a day, so for many users a real provider and a verified domain are still needed (Q-38).
   `PUBLIC_URL` is the laptop's VPN address, so the unsubscribe link only opens on that network.
4. ~~Schedule the daily refresh~~ registered on 2026-11-22 (task `PharmaviqueDailyRefresh`, 03:00; the laptop must be on).
   The exit code 3 of 2026-11-21 was a lost internet connection (`ERR_NAME_NOT_RESOLVED` at list page 442 of 459),
   not a block. `daily_refresh.ps1` now waits 10 minutes and resumes the same run up to three times, only for network
   errors; a block (401/403/429) or a robots.txt refusal is never retried.
5. ~~`localhost` to `127.0.0.1` in `.env`~~ done.
6. Delete the stray file `C:\LUsers\x` (created by mistake; removal was blocked).
7. Decide about real photos for measuring the scans (Q-32) and a pharmacist reviewing similar names (Q-26).

## 7. What is next

README section 19 is the ordered list. In short: real-phone fixes; real photos and `scan_eval.py`;
shortage and safety-notice alerts (the list loader emits no events); class allergies, password reset,
change of email; exact pharmacy locations (Q-39); the app using the jobs endpoints; deployment for many
users (load balancer, PgBouncer, replica, managed Redis, CDN, object storage); Egypt as a CSV adapter.

## 8. Known limits (do not claim more than this)

- Scans were measured on **generated, clean pictures only** (names read 100%, no invented lines, no dose
  read). Real glare, angles and handwriting are unmeasured.
- Pharmacy addresses are a city plus a national-address code: "nearby" is by city. 32 of 34 cities have a
  point (Al-Namas failed a region sanity check, Alhafoof was not found); the points are unreviewed.
- Similar-name warnings: 605 of 4,859 brands (12%) have a strong match; no pharmacist has reviewed them.
- Interaction data (DDInter, openFDA) is incomplete and matches by ingredient name: "nothing found" is
  never "safe".
- Row-level security does nothing for a database superuser: production must connect as an ordinary role.
- Drugs: the daily update loads what it read even when a run is partial (`data/refresh/ATTENTION.md` says
  what was not checked). A drug that left the SFDA list is withdrawn only after it is missing from two
  complete runs in a row, at most 50 at once (`sfda-withdraw-absent`, Q-40: both numbers are guesses). A
  change that is only in a details page can take up to a month to be seen (`--recheck 300`).
- Not built: Redis failover, replicas, CDN, shared picture storage, the pictures image on ghcr (the push
  never completed; the pictures exist only on the laptop), push notifications (dropped), the Egypt adapter.

## 9. Verification record (2026-11-22)

- 1,336 tests collected; the full suite including integration passed before the last changes; CI green on
  the pushed commits.
- Run for real on the development database: sign-up, 403 before confirming, wrong code 400, right code
  200, a digest email for a real product's price change, unsubscribe, deletion; the history check
  (aspirin with warfarin: major, `ddinter-2.0`); the pharmacies endpoints; the load test (single process:
  about 1,000 requests a second from the cache at 10 users, see `docs/PERFORMANCE.md`).
- Faults found by those real runs and fixed: the console email crashed printing Arabic on Windows; an
  empty `PHARMAVIQUE_REDIS_URL` crashed start-up; a wrong geocoder point (Al-Namas) was rejected.

## 10. Git

Branch `main`, remote `origin` = https://github.com/Eslamusamaaa/Pharmavique. Untracked files that must
stay out of commits: `claude-code-prompt.md`, `expo-go-qr.png`, `data/media/placeholders/`. `data/` is
git-ignored (databases dumps, crawls, pictures); `data/README.md` says how to rebuild each folder.
