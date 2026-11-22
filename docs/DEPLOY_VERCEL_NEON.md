# Deploying on Vercel and Neon

State of 2026-11-22: a proof of concept on the free plans of both services. One Vercel project
(`pharmavique`, Hobby plan, region `fra1`) runs the API and serves the website; one Neon project
(`pharmavique`, Free plan, AWS Frankfurt) holds the database.

```
phone / computer ──▶ Vercel (FastAPI as one Python function + the exported website)
                              │
                              └──▶ Neon (Postgres 18, pgvector, pg_trgm)
```

## What is where

| Part | Where | Notes |
|---|---|---|
| API and website | Vercel function `app.py` | `PHARMAVIQUE_WEB_DIR=mobile/dist`; the site is built on Vercel by `vercel.json` (`cd mobile && npm ci && npm run build:web`) |
| Database | Neon | one project, branch `production`; use the pooled address in Vercel |
| Pictures | placeholders for now | the app draws its own; see "Pictures" |
| Daily refresh of SFDA data | not on Vercel | needs Chromium and hours; see `docs/SCRAPING_ON_GITHUB.md` |

## Environment variables (Vercel, Production)

Set in the Vercel dashboard (Settings, Environment Variables). Secrets are never committed.

- `PHARMAVIQUE_DATABASE_URL`: the **pooled** Neon address, exactly as the Neon console shows it
  (`postgresql://…-pooler…?sslmode=require&channel_binding=require`). `foundation/db/url.py` turns
  it into the form the async driver accepts, so it is pasted unchanged.
- `PHARMAVIQUE_JWT_SECRET` (32 or more random characters), `PHARMAVIQUE_PUBLIC_URL`.
- `PHARMAVIQUE_ENVIRONMENT=prod`, `PHARMAVIQUE_WEB_DIR=mobile/dist`,
  `PHARMAVIQUE_TRUSTED_PROXY_HOPS=1` (without it the rate limit sees one caller: Vercel's address).
- The provider keys from `.env.example` (Groq, OpenRouter, ElevenLabs, Tavily, Cloudflare), and the
  e-mail settings.
- No Redis: `PHARMAVIQUE_REDIS_URL` stays unset. The app never calls `/v1/jobs`, and without Redis
  the cache and rate limit are per instance, which is acceptable at this size.

## Moving the data to Neon

1. Create the Neon project. Take the **direct** (unpooled) address for these steps.
2. `PHARMAVIQUE_DATABASE_URL=<direct address> uv run alembic upgrade heads`
3. `NEON_DIRECT_URL=<direct address> bash scripts/db_copy_remote.sh`. It copies the tables of the
   `catalog`, `search`, `knowledge` and `interactions` schemas from the local database in pieces of
   about 3 MB, retrying a piece that fails: one long transfer over the internet was dropped
   (`SSL error: unexpected eof`) every time. People's data (identity, watchlist) is not copied.
4. `PHARMAVIQUE_DATABASE_URL=<direct address> uv run pharmavique analytics-rebuild`
5. `alembic current` must list the seven heads; `scripts/db_copy_remote.sh` does not touch
   `public.alembic_version`.

Do not restore the committed `data/db/*.dump` files with `--clean` after the migrations: they were made
before `catalog.city_locations` existed and the schema drop fails.

## Things that broke on Vercel, and why they are fixed the way they are

- **Pillow** was in the dev group only: the function failed to start. It is a runtime dependency now,
  and `tests/unit/test_runtime_dependencies.py` fails when product code imports a package that is not.
- **Fonts answered 404 and the page stayed blank**: the export puts them under
  `dist/assets/node_modules/`, a folder name Vercel's Python bundler drops. `build-web.mjs` renames it
  to `assets/vendor` and rewrites the references.
- **A new deployment kept showing the old page**: Vercel gives every file the same modification
  date, so the ETag of a new `index.html` of the same size equalled the old one and browsers kept the
  old page, which asked for scripts that no longer existed. The page shell, the manifest and the icons
  are served with `Cache-Control: no-store` and without `ETag` or `Last-Modified` (the host's edge
  answers 304 on its own whenever an ETag matches); files under `_expo/static/` and `assets/` carry a
  content hash and are cached for a year.
- **Logo with white edges**: `logo-h.png` and `mark.png` had an opaque light background; it is
  transparent now. The favicon is the full-bleed icon.

## Limits to remember (Hobby plan, from the Vercel and Neon documentation, 2026-11-22)

- Function duration 300 s, memory 2 GB, request body 4.5 MB (photos are sent at JPEG quality 0.7).
- Source upload 100 MB with the CLI: `.vercelignore` keeps `data/`, tests and docs out.
- Neon Free: 1 GB per project, 100 CU-hours a month, compute sleeps after 5 minutes idle.
- Vercel Cron on Hobby runs once a day at most.

## Pictures

The 6,320 picture files (832 MB) are not in git and do not fit the Hobby upload limit. Neon object
storage (5 GB free, public buckets) is the planned home; until then every product shows the app's
own placeholder.
