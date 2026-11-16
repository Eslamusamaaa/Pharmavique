# Pharmavique: rules for every session

Full brief: `docs/PROJECT_BRIEF.md`. Architecture: `docs/ARCHITECTURE.md`. Decisions: `docs/adr/`. Unknowns: `docs/OPEN_QUESTIONS.md`.

## What this is
Multi-tenant drug-intelligence API (patient, pharmacist, pharma company) on official registry data. Markets: Saudi Arabia first, Egypt as a pluggable adapter. Modular monolith, DDD, onion architecture. API first.

## Architecture rules (enforced by `uv run lint-imports` in CI)
- Nine contexts under `src/pharmavique/<context>/` with `contracts`, `domain`, `application`, `infrastructure`, `presentation`.
- Dependencies point inward. `domain` and `application` import no frameworks (sqlalchemy, fastapi, pydantic, redis, arq, httpx, alembic) and no other context.
- Contexts talk only through `<provider>.contracts`, from an adapter module listed in the allow-list (`context-independence` contract in `pyproject.toml`). Changes happen through the transactional outbox and integration events.
- One Postgres schema per context. No cross-schema foreign keys or joins.
- `bootstrap` is the only place that wires everything. Nothing imports it.

## Domain rules
- Equivalence = same active-ingredient set, same strength per ingredient after unit normalization, same dosage-form family. Anything uncertain is "possible, needs pharmacist check", never "equivalent".
- Never medical advice: no dosing, never "stop" or "switch". The pharmacist or doctor decides.
- Every record has provenance (source, source URL/file, fetched_at, snapshot id) and a `trust` level (`official`, `unofficial_unverified`).
- Never assume currencies or price units. Store `currency` per market; undocumented means `unconfirmed`, surfaced in the API.
- LLM answers only from retrieved leaflet chunks or catalog data, with citations; if nothing is retrieved, say so.
- Normalize Arabic (diacritics, alef/ya/ta marbuta variants, Arabic-Indic digits); keep an alias table; test misspellings.

## Data and compliance
- SA: official SFDA API with the user's key from env vars, plus a file-import fallback. Check real response schemas; never invent fields.
- EG: **no scraping, no CAPTCHA bypass.** CSV-import adapter, marked `unofficial_unverified`.
- Throttle outbound calls, clear User-Agent, cache. Record license status per source in `docs/DATA_SOURCES.md`.
- Health data is sensitive: minimum collection, encrypt at rest, delete uploads after processing unless opted in, never log it.
- No secrets in the repo. `.env.example` only.

## Working agreements
- Plan before coding; per phase write the plan, list assumptions and questions, wait for approval.
- Tests before adapters; every bug fix starts with a failing test. No unrelated refactors.
- Never fabricate data, API fields, endpoints, prices or medical facts. Unknown goes in `docs/OPEN_QUESTIONS.md`.
- Done means: `ruff check`, `ruff format --check`, `mypy src tests`, `lint-imports`, `pytest` all pass (report real output), docs/ADRs updated, migrations reversible.

## Git rules (owner's instruction)
- Every commit and push is authored by the repository owner only: their name and email. **Never** add `Co-Authored-By`, "Generated with", or any mention of Claude or an AI tool in commit messages, PR descriptions or authorship.
- Split commits by unit of work (one logical change per commit, with a clear message). Do not lump unrelated work into one commit.
