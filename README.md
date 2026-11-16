# Pharmavique

Drug intelligence platform for Saudi Arabia and Egypt. Modular monolith, DDD, onion architecture.
API first. Nothing this system returns is medical advice: the pharmacist or doctor decides.

Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md).

## Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker (for Postgres and Redis).

```bash
cp .env.example .env            # edit the placeholder password
uv sync                         # install runtime + dev dependencies
docker compose up -d db redis   # Postgres (pg_trgm + pgvector) and Redis
uv run uvicorn pharmavique.bootstrap.api:create_app --factory --reload
# http://127.0.0.1:8000/health   and   http://127.0.0.1:8000/docs
```

> The project folder is inside OneDrive. Keep the virtualenv outside it to avoid syncing thousands
> of files, for example: `UV_PROJECT_ENVIRONMENT=$HOME/.venvs/pharmavique uv sync`.

## Checks (run before any commit)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run lint-imports            # architecture contracts: a violation fails the build
uv run pytest
```

## Layout

`src/pharmavique/<context>/{contracts,domain,application,infrastructure,presentation}` for each of the
nine bounded contexts, plus `shared_kernel`, `foundation` and `bootstrap` (composition root).
See [docs/REPOSITORY_STRUCTURE.md](docs/REPOSITORY_STRUCTURE.md). Decisions live in `docs/adr/`,
unknowns in [docs/OPEN_QUESTIONS.md](docs/OPEN_QUESTIONS.md).
