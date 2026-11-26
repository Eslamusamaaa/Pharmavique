# Production image for the API and the job worker (self-hosted deployment, docs/RUNBOOK.md).
# Differs from the development Dockerfile at the root: no SFDA crawler browser, migrations included,
# a /ready health check, and the build tools stay in the builder stage.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations
# alembic.ini reads each context's migration versions from src/ (one folder per context)
COPY --chown=app:app src ./src

USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PHARMAVIQUE_ENVIRONMENT=prod
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=8s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=7).status == 200 else 1)"

CMD ["uvicorn", "pharmavique.bootstrap.api:create_app", "--factory", "--host", "0.0.0.0", \
     "--port", "8000", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
