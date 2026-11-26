# Runbook

What to do when something is wrong with production, and how to roll back, restore and move hosts.
Production today: Vercel (API + website, project `pharmavique`, region `fra1`) and Neon (Postgres,
branch `production`). Details of that setup: `docs/DEPLOY_VERCEL_NEON.md`.

## 1. Health checks

| Path | Answers | Use it for |
|---|---|---|
| `GET /health` | always 200 while the process runs; version and environment | "is the function up" |
| `GET /ready` | 200 `ready` or 503 `not_ready`, with `checks.database` and `checks.shared_store` (`ok`, `failed`, `not_configured`) | "can it serve data"; Docker health check; uptime monitors |

- Each check has a 5 s limit. A Neon compute waking from idle answers in 1 to 3 s, so the first
  `/ready` after a quiet spell is slower but still `ready`.
- `/ready` never shows addresses or error text. The failing check's error type is in the logs
  (`ready check failed`, with `check` and `error`).
- Without a database: `ready` in dev, `not_ready` in prod.
- Both are exempt from the rate limit.

```
curl -s https://pharmavique.vercel.app/ready
```

## 2. The site is down or slow

1. `curl -s https://pharmavique.vercel.app/health`. No answer: Vercel side, go to step 2. Answer:
   go to step 3.
2. Vercel dashboard, project `pharmavique`, Deployments: did the latest production build fail, or
   did a new deployment start the trouble? If the latest deployment is the cause, roll back (section 3).
   Also check the Vercel status page.
3. `curl -s https://pharmavique.vercel.app/ready`:
   - `database: failed`: open the Neon console. Look for the compute being suspended or over its
     monthly compute-hours, the project being over its storage limit, or a changed password. A changed
     address or password means updating `PHARMAVIQUE_DATABASE_URL` in Vercel and redeploying.
   - `ready`: the data path works. Look at Sentry (errors and slow requests) and the Vercel function
     logs (`vercel logs pharmavique.vercel.app`) for the failing route.
4. One feature is misbehaving (assistant, scan, voice, sources page): turn it off without a code
   change. Set `PHARMAVIQUE_FEATURE_<NAME>=false` in Vercel (names at `GET /v1/features`) and redeploy;
   environment variables only reach new deployments.
5. A model provider is down: the assistant falls back to the next configured free model on its own;
   if all are down it answers 503 and the rest of the app keeps working.

## 3. Roll back a bad deployment (Vercel)

Every push to `main` makes a new production deployment; the previous ones stay available.

- Dashboard: Deployments, open the last good production deployment, menu, **Instant Rollback**.
- CLI: `vercel rollback <url-of-the-good-deployment>` (or `vercel rollback` for the previous one).

After a rollback Vercel stops pointing the production domain at new deployments until you promote one
again. Fix the code, push, then promote the new deployment (dashboard **Promote**, or
`vercel promote <url>`). Write down which deployment was rolled back and why.

A rollback does not touch the database. A deployment that ran a migration may need the migration
undone too (section 5).

## 4. Restore the database (Neon)

Neon keeps the history of each branch for a restore window that depends on the plan (see the project's
settings in the Neon console). Within it any earlier moment can be brought back.

**Look first, then restore.**

1. Neon console, Branches, **Create branch** from `production`, choosing the moment before the damage
   (point in time). Name it `restore-<date>`.
2. Compare it with production (read-only):

   ```
   uv run python scripts/restore_drill.py "<production direct address>" "<restore branch direct address>"
   ```

   It prints every table's row count on both sides and the migration versions. Check the tables you
   expect to differ, and that nothing else does.
3. Choose:
   - **Point production back**: Neon console, branch `production`, **Restore** to that moment. Neon
     keeps a backup branch of the state before the restore.
   - **Copy back a few rows**: read them from the restore branch and write them into production.
4. Delete the `restore-<date>` branch when done (branches count toward the plan's limits).

Outside the restore window: the latest local snapshot (`scripts/db_snapshot.sh` writes
`data/db/<schema>.dump`; `scripts/db_restore.sh` loads it into the local Postgres), then copy it up the
way `docs/DEPLOY_VERCEL_NEON.md` ("Moving the data to Neon") describes. The daily refresh can also
rebuild catalog data from SFDA from scratch; user accounts and lists exist only in the database.

### Restore drill (run once now, then after every large schema change)

The drill proves the steps above work before they are needed. It writes nothing to production.

1. Create `restore-drill-<date>` from `production` at a moment about an hour ago (step 1 above).
2. Run `scripts/restore_drill.py` against both (step 2). The expected result: catalog tables equal
   or a few rows apart (the refresh may have run since), migrations equal.
3. Point a local API at the drill branch (`PHARMAVIQUE_DATABASE_URL=<drill pooled address>`), start it
   and check `/ready` and one search.
4. Delete the drill branch. Record the result below.

| Date | Who | Branch moment | Tables differing | Migrations | `/ready` on branch | Notes |
|---|---|---|---|---|---|---|
| (not run yet) | | | | | | needs the owner's Neon console |

## 5. Migrations

- Production migrations run only from the **Database migrate** GitHub workflow (by hand). It prints
  what the migrations would remove and copies the catalog schema first, and never runs during the daily
  refresh.
- Every migration has a `downgrade`. To undo the last one of a context, run it locally against the
  direct address: `PHARMAVIQUE_DATABASE_URL=<direct address> uv run alembic downgrade <context>@-1`.
  Check that no newer code depends on it first (roll the deployment back before the schema).

### Password reset needs the identity migration first

Choosing a new password with an emailed code (ADR-023) adds a column to `identity.email_codes`
(`identity_0004`). Run **Database migrate** *before* the deployment that has it: the old code keeps
working on the new column, but the new code writes it, so deploying first makes sign-up fail until the
migration runs. To undo: roll the deployment back, then `alembic downgrade identity@-1` (reset codes are
dropped, sign-up codes kept).

### Saved conversations need their schema

The assistant's saved conversations (ADR-022) live in the `assistant` schema. After a deployment that
adds it, run **Database migrate** once. Until then the assistant still answers, nothing is saved, and
the conversation list answers with an error. Switching the feature off:
`PHARMAVIQUE_FEATURE_CHAT_HISTORY=false` in Vercel, then redeploy.

## 6. Daily data refresh failed

GitHub emails the repository owner when the **Daily refresh** workflow fails. Open the run, read the
step that failed (one JSON event per step in its log), fix the cause, and start it again by hand
(Actions, Daily refresh, **Run workflow**). A failed refresh leaves yesterday's data in place: the
sources page shows the older "last successful update".

## 7. Secrets

- All secrets live in Vercel environment variables and GitHub Actions secrets, never in git.
- Changing `PHARMAVIQUE_JWT_SECRET` (32+ characters, production refuses to start otherwise) signs
  everyone out. Do it when it may have leaked.
- After changing any variable in Vercel, redeploy.

## 8. Moving to Docker (self-hosted)

Ready for a later move off Vercel + Neon; not used today. Files: `docker/production/` (API and
worker image, compose file, `.env.example`) and `docker/pgbouncer/` (connection pooler).

```
cp docker/production/.env.example docker/production/.env      # fill it in, never commit it
docker compose -f docker/production/compose.yml --env-file docker/production/.env build
docker compose -f docker/production/compose.yml --env-file docker/production/.env run --rm migrate
docker compose -f docker/production/compose.yml --env-file docker/production/.env up -d
curl -s http://127.0.0.1:8000/ready
```

- Postgres is outside the compose file: a managed Postgres with `vector` and `pg_trgm`, or Neon's
  direct address. PgBouncer (transaction pooling, with prepared statements kept, which asyncpg needs)
  sits between the API and it; migrations go to the direct address.
- The API container is healthy only while `/ready` answers 200. It is published on
  `127.0.0.1:8000` only: put a reverse proxy with TLS in front, and set
  `PHARMAVIQUE_TRUSTED_PROXY_HOPS=1`.
- Redis is included, so the cache, the rate limit and the job queue are shared across API workers,
  and the `worker` container runs scans and assistant jobs (it needs a scan or assistant model key).
- Product pictures: not in this image (see "Pictures" in `docs/DEPLOY_VERCEL_NEON.md`).
- Tested locally on 2026-11-26 against the development database: image builds, migrations run,
  `/ready` 200 through PgBouncer, a search answers, and `/ready` turns 503 when PgBouncer stops.
- Switching over: run both side by side, restore a copy of the database, point DNS at the new host,
  watch `/ready` and Sentry, keep Vercel as the rollback for a week.
