FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first (cached layer), then the project itself.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra scraper --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --extra scraper

RUN useradd --create-home --uid 10001 app
USER app

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

CMD ["uvicorn", "pharmavique.bootstrap.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
