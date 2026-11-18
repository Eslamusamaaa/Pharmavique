"""FastAPI application factory. Run with: uvicorn pharmavique.bootstrap.api:create_app --factory.

Routers are mounted here and nowhere else. The data endpoints need Postgres (migrated and loaded);
without `PHARMAVIQUE_DATABASE_URL` they answer 503 and `/health` still works. The assistant also
needs a language-model key; without one it answers 503 and everything else still works.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.bootstrap import api_assistant, api_drugs, health
from pharmavique.bootstrap.ai import build_assistant
from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.contracts.queries import CatalogDetails, CatalogQueries
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.search.application.handlers import SearchProductsHandler
from pharmavique.search.contracts.queries import ProductSearch
from pharmavique.search.infrastructure.postgres import PostgresSearchIndex
from pharmavique.substitution.application.compare import CompareProductsHandler
from pharmavique.substitution.contracts.queries import EquivalenceQueries


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = None
    injected = (app.state.search, app.state.catalog, app.state.details, app.state.assistant)
    if all(backend is None for backend in injected):
        settings = get_settings()
        secret = settings.database_url
        if secret is not None:
            engine = create_engine(secret.get_secret_value())
            session_factory = create_session_factory(engine)
            app.state.search = SearchProductsHandler(PostgresSearchIndex(session_factory))
            catalog = ReadProductCardsHandler(SqlAlchemyProductReader(session_factory))
            app.state.catalog = catalog
            app.state.details = catalog
            app.state.assistant = build_assistant(
                settings,
                session_factory,
                search=app.state.search,
                catalog=catalog,
                equivalence=app.state.equivalence,
            )
    try:
        yield
    finally:
        if engine is not None:
            await engine.dispose()


def create_app(
    search: ProductSearch | None = None,
    catalog: CatalogQueries | None = None,
    cors_origins: list[str] | None = None,
    details: CatalogDetails | None = None,
    equivalence: EquivalenceQueries | None = None,
    assistant: AskAssistant | None = None,
) -> FastAPI:
    """Backends are injected by tests; else built at startup from settings."""
    app = FastAPI(
        title="Pharmavique API",
        summary="Drug intelligence platform (SA + EG).",
        description=(
            "Informational only. Nothing returned by this API is medical advice; "
            "the pharmacist or doctor decides."
        ),
        lifespan=_lifespan,
    )
    app.state.search = search
    app.state.catalog = catalog
    app.state.details = details
    app.state.equivalence = equivalence or CompareProductsHandler()
    app.state.assistant = assistant
    origins = get_settings().cors_origins if cors_origins is None else cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
    app.include_router(health.router)
    app.include_router(api_drugs.router)
    app.include_router(api_assistant.router)
    return app
