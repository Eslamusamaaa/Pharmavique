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
from pharmavique.bootstrap import (
    api_assistant,
    api_drugs,
    api_pictures,
    api_recognition,
    api_voice,
    health,
    observability,
)
from pharmavique.bootstrap.ai import build_assistant, build_scanner, build_voice
from pharmavique.bootstrap.api_pictures import PictureLookup
from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.contracts.queries import CatalogDetails, CatalogQueries
from pharmavique.catalog.infrastructure.persistence.pictures import SqlAlchemyPictureStore
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.search.application.handlers import SearchProductsHandler
from pharmavique.search.contracts.queries import ProductSearch
from pharmavique.search.infrastructure.postgres import PostgresSearchIndex
from pharmavique.substitution.application.compare import CompareProductsHandler
from pharmavique.substitution.contracts.queries import EquivalenceQueries
from pharmavique.voice.application.speak import Speak, Transcribe
from pharmavique.voice.infrastructure.audio_cache import AudioCache


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = None
    injected = (
        app.state.search,
        app.state.catalog,
        app.state.details,
        app.state.assistant,
        app.state.speak,
        app.state.transcribe,
        app.state.scanner,
    )
    if all(backend is None for backend in injected):
        settings = get_settings()
        app.state.transcribe, app.state.speak = build_voice(settings)
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
                observer=observability.LoggingAssistantObserver(app.state.metrics),
            )
            app.state.scanner = build_scanner(settings, search=app.state.search, catalog=catalog)
            app.state.pictures = SqlAlchemyPictureStore(session_factory)
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
    speak: Speak | None = None,
    transcribe: Transcribe | None = None,
    scanner: ScanImage | None = None,
    pictures: PictureLookup | None = None,
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
    app.state.speak = speak
    app.state.transcribe = transcribe
    app.state.scanner = scanner
    app.state.pictures = pictures
    app.state.metrics = observability.Metrics()
    app.state.audio_cache = AudioCache()
    app.add_middleware(observability.RequestContextMiddleware, metrics=app.state.metrics)
    origins = get_settings().cors_origins if cors_origins is None else cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
    app.include_router(health.router)
    app.include_router(observability.router)
    app.include_router(api_drugs.router)
    app.include_router(api_pictures.router)
    app.include_router(api_assistant.router)
    app.include_router(api_voice.router)
    app.include_router(api_recognition.router)
    return app
