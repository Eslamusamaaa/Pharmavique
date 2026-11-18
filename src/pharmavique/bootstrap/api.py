"""FastAPI application factory. Run with: uvicorn pharmavique.bootstrap.api:create_app --factory.

Routers are mounted here and nowhere else. The data endpoints need Postgres (migrated and loaded);
without `PHARMAVIQUE_DATABASE_URL` they answer 503 and `/health` still works.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pharmavique.bootstrap import api_drugs, health
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
    if app.state.search is None and app.state.catalog is None and app.state.details is None:
        secret = get_settings().database_url
        if secret is not None:
            engine = create_engine(secret.get_secret_value())
            session_factory = create_session_factory(engine)
            app.state.search = SearchProductsHandler(PostgresSearchIndex(session_factory))
            catalog = ReadProductCardsHandler(SqlAlchemyProductReader(session_factory))
            app.state.catalog = catalog
            app.state.details = catalog
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
    origins = get_settings().cors_origins if cors_origins is None else cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"]
        )
    app.include_router(health.router)
    app.include_router(api_drugs.router)
    return app
