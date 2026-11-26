"""FastAPI application factory. Run with: uvicorn pharmavique.bootstrap.api:create_app --factory.

Routers are mounted here and nowhere else. The data endpoints need Postgres (migrated and loaded);
without `PHARMAVIQUE_DATABASE_URL` they answer 503 and `/health` still works. The assistant also
needs a language-model key; without one it answers 503 and everything else still works.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pharmavique.analytics.application.service import AnalyticsService
from pharmavique.analytics.infrastructure.catalog_source import CatalogMarketSource
from pharmavique.analytics.infrastructure.postgres import PostgresAnalyticsStore
from pharmavique.analytics.infrastructure.refresh_files import FileRefreshHistory
from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.history import ConversationService, TitleWriter
from pharmavique.assistant.infrastructure.postgres_history import PostgresConversationStore
from pharmavique.bootstrap import (
    api_assistant,
    api_auth,
    api_company,
    api_compare,
    api_conversations,
    api_drugs,
    api_history,
    api_interactions,
    api_jobs,
    api_lasa,
    api_me,
    api_operator,
    api_pharmacies,
    api_pictures,
    api_recognition,
    api_shelf,
    api_shortage,
    api_sources,
    api_voice,
    features,
    health,
    observability,
)
from pharmavique.bootstrap.ai import (
    build_assistant,
    build_name_extractor,
    build_scanner,
    build_title_writer,
    build_voice,
)
from pharmavique.bootstrap.api_pictures import PictureLookup
from pharmavique.bootstrap.identity_wiring import build_email_sender, build_identity
from pharmavique.bootstrap.job_handlers import build_handlers
from pharmavique.bootstrap.monitoring import init_monitoring
from pharmavique.bootstrap.rate_limit import RateLimitMiddleware
from pharmavique.bootstrap.settings import check_signing_secret, get_settings
from pharmavique.bootstrap.sources_status import SourceStatusReader, SqlAlchemySourceStatusReader
from pharmavique.bootstrap.web_app import mount_web_app
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.contracts.queries import (
    CatalogDetails,
    CatalogIngredients,
    CatalogListItems,
    CatalogPharmacies,
    CatalogQuality,
    CatalogQueries,
)
from pharmavique.catalog.infrastructure.persistence.list_items import SqlAlchemyListItemReader
from pharmavique.catalog.infrastructure.persistence.pharmacies import SqlAlchemyPharmacyReader
from pharmavique.catalog.infrastructure.persistence.pictures import SqlAlchemyPictureStore
from pharmavique.catalog.infrastructure.persistence.price_changes import (
    SqlAlchemyIngredientReader,
    SqlAlchemyPriceChangeReader,
)
from pharmavique.catalog.infrastructure.persistence.quality import SqlAlchemyQualityReader
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.arq_jobs import ArqJobQueue
from pharmavique.foundation.clock import SystemClock
from pharmavique.foundation.db.engine import create_engine, create_session_factory, ping_database
from pharmavique.foundation.jobs import InlineJobQueue, JobQueue, JobRunner
from pharmavique.foundation.kv import KeyValueStore, RedisStore, redis_client
from pharmavique.foundation.read_cache import ReadCache
from pharmavique.identity.application.service import IdentityService
from pharmavique.identity.contracts import TokenVerifier
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.interactions.application.check import CheckInteractions
from pharmavique.interactions.application.contraindications import ListContraindications
from pharmavique.interactions.contracts.queries import ContraindicationChecks, InteractionChecks
from pharmavique.interactions.infrastructure.postgres import (
    PostgresContraindicationStore,
    PostgresInteractionStore,
)
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.search.application.handlers import SearchProductsHandler
from pharmavique.search.contracts.queries import ProductSearch
from pharmavique.search.infrastructure.postgres import PostgresSearchIndex
from pharmavique.search.infrastructure.similar_names import PostgresSimilarNameStore
from pharmavique.shared_kernel.email import EmailSender
from pharmavique.substitution.application.compare import CompareProductsHandler
from pharmavique.substitution.contracts.queries import EquivalenceQueries
from pharmavique.voice.application.extract import ExtractDrugName
from pharmavique.voice.application.ports import DrugNameExtractor
from pharmavique.voice.application.speak import Speak, Transcribe
from pharmavique.voice.infrastructure.audio_cache import LocalAudioStore, SharedAudioStore
from pharmavique.watchlist.application.service import WatchlistService
from pharmavique.watchlist.application.shelf import ShelfService
from pharmavique.watchlist.infrastructure.postgres import PostgresWatchlistStore


def use_shared_store(app: FastAPI, store: KeyValueStore, cache_ttl_seconds: int) -> None:
    """Everything the API instances must share lives in one store: the rate limit, the read
    cache and spoken-answer links. Without a store each instance keeps its own, which is only
    right for a single instance."""
    metrics: observability.Metrics = app.state.metrics
    app.state.kv = store
    app.state.read_cache = ReadCache(
        store,
        ttl_seconds=cache_ttl_seconds,
        observer=lambda namespace, result: metrics.inc(
            "pharmavique_cache_total", {"namespace": namespace, "result": result}
        ),
    )
    app.state.audio_cache = SharedAudioStore(store)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = None
    redis_store: RedisStore | None = None
    arq_queue: ArqJobQueue | None = None
    injected = (
        app.state.search,
        app.state.catalog,
        app.state.details,
        app.state.assistant,
        app.state.speak,
        app.state.transcribe,
        app.state.scanner,
        app.state.identity,
    )
    if all(backend is None for backend in injected):
        settings = get_settings()
        app.state.transcribe, app.state.speak = build_voice(settings)
        if settings.redis_url is not None and app.state.kv is None:
            # short timeouts: a slow Redis must cost a request milliseconds, never seconds
            redis_store = RedisStore(
                redis_client(settings.redis_url.get_secret_value(), timeout=0.25)
            )
            use_shared_store(app, redis_store, settings.cache_ttl_seconds)
        app.state.extract_name = ExtractDrugName(build_name_extractor(settings))
        secret = settings.database_url
        if secret is not None:
            engine = create_engine(
                secret.get_secret_value(),
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
            )
            session_factory = create_session_factory(engine)
            app.state.database_ping = partial(ping_database, engine)
            app.state.search = SearchProductsHandler(PostgresSearchIndex(session_factory))
            reader = SqlAlchemyProductReader(session_factory)
            catalog = ReadProductCardsHandler(reader, SqlAlchemyPriceChangeReader(session_factory))
            app.state.catalog_names = reader
            app.state.similar_names = PostgresSimilarNameStore(session_factory)
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
            if app.state.kv is not None:
                runner = JobRunner(
                    app.state.kv, build_handlers(app.state.scanner, app.state.assistant)
                )
                if settings.job_backend == "arq" and settings.redis_url is not None:
                    arq_queue = await ArqJobQueue.connect(
                        runner, settings.redis_url.get_secret_value()
                    )
                    app.state.jobs = arq_queue
                else:
                    app.state.jobs = InlineJobQueue(runner)
            app.state.pictures = SqlAlchemyPictureStore(session_factory)
            app.state.list_items = SqlAlchemyListItemReader(session_factory)
            app.state.ingredients = SqlAlchemyIngredientReader(session_factory)
            app.state.watchlist = WatchlistService(
                PostgresWatchlistStore(session_factory), SystemClock()
            )
            app.state.shelf = ShelfService(PostgresWatchlistStore(session_factory), SystemClock())
            app.state.analytics = AnalyticsService(
                PostgresAnalyticsStore(session_factory),
                CatalogMarketSource(catalog),
                SystemClock(),
            )
            app.state.quality = SqlAlchemyQualityReader(session_factory)
            app.state.source_status = SqlAlchemySourceStatusReader(session_factory)
            app.state.pharmacies = SqlAlchemyPharmacyReader(session_factory)
            app.state.refresh_history = FileRefreshHistory(Path(settings.refresh_dir))
            if settings.jwt_secret is not None:
                tokens = JwtAccessTokens(settings.jwt_secret.get_secret_value())
                app.state.token_verifier = tokens
                app.state.identity = build_identity(settings, session_factory, tokens)
                app.state.email_sender = build_email_sender(settings)
                app.state.unsubscribe_secret = settings.jwt_secret.get_secret_value()
            app.state.interactions = CheckInteractions(PostgresInteractionStore(session_factory))
            app.state.conversations = ConversationService(
                PostgresConversationStore(session_factory), SystemClock()
            )
            if app.state.title_writer is None:
                app.state.title_writer = build_title_writer(settings)
            app.state.contraindications = ListContraindications(
                PostgresContraindicationStore(session_factory)
            )
    try:
        yield
    finally:
        if engine is not None:
            await engine.dispose()
        if arq_queue is not None:
            await arq_queue.close()
        if redis_store is not None:
            await redis_store.close()


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
    name_extractor: DrugNameExtractor | None = None,
    interactions: InteractionChecks | None = None,
    contraindications: ContraindicationChecks | None = None,
    list_items: CatalogListItems | None = None,
    identity: IdentityService | None = None,
    email_sender: EmailSender | None = None,
    unsubscribe_secret: str | None = None,
    watchlist: WatchlistService | None = None,
    shelf: ShelfService | None = None,
    shelf_scan_enabled: bool | None = None,
    ingredients: CatalogIngredients | None = None,
    token_verifier: TokenVerifier | None = None,
    store: KeyValueStore | None = None,
    jobs: JobQueue | None = None,
    jobs_per_user_per_minute: int | None = None,
    job_max_queue_depth: int | None = None,
    analytics: AnalyticsService | None = None,
    quality: CatalogQuality | None = None,
    source_status: SourceStatusReader | None = None,
    pharmacies: CatalogPharmacies | None = None,
    refresh_history: FileRefreshHistory | None = None,
    rate_limit_per_minute: int | None = None,
    heavy_rate_limit_per_minute: int | None = None,
    trusted_proxy_hops: int | None = None,
    conversations: ConversationService | None = None,
    title_writer: TitleWriter | None = None,
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
    app.state.list_items = list_items
    app.state.lasa = None
    app.state.catalog_names = None
    app.state.similar_names = None
    app.state.identity = identity
    app.state.email_sender = email_sender
    app.state.unsubscribe_secret = unsubscribe_secret
    app.state.watchlist = watchlist
    app.state.shelf = shelf
    app.state.ingredients = ingredients
    app.state.token_verifier = token_verifier
    app.state.analytics = analytics
    app.state.quality = quality
    app.state.source_status = source_status
    app.state.pharmacies = pharmacies
    app.state.pharmacy_directories = {}
    app.state.refresh_history = refresh_history
    app.state.interactions = interactions
    app.state.conversations = conversations
    app.state.title_writer = title_writer
    app.state.contraindications = contraindications
    app.state.extract_name = ExtractDrugName(name_extractor)
    app.state.metrics = observability.Metrics()
    app.state.audio_cache = LocalAudioStore()
    app.state.kv = None
    app.state.database_ping = None
    app.state.read_cache = None
    app.state.jobs = jobs
    app.add_middleware(observability.RequestContextMiddleware, metrics=app.state.metrics)
    if store is not None:
        use_shared_store(app, store, get_settings().cache_ttl_seconds)
    settings = get_settings()
    check_signing_secret(settings)
    init_monitoring(settings)
    app.state.shelf_scan_enabled = (
        settings.shelf_scan_enabled if shelf_scan_enabled is None else shelf_scan_enabled
    )
    app.state.job_limits = api_jobs.JobLimits(
        per_user_per_minute=settings.jobs_per_user_per_minute
        if jobs_per_user_per_minute is None
        else jobs_per_user_per_minute,
        max_queue_depth=settings.job_max_queue_depth
        if job_max_queue_depth is None
        else job_max_queue_depth,
        trusted_proxy_hops=settings.trusted_proxy_hops
        if trusted_proxy_hops is None
        else trusted_proxy_hops,
    )
    app.add_middleware(
        RateLimitMiddleware,
        general=settings.rate_limit_per_minute
        if rate_limit_per_minute is None
        else rate_limit_per_minute,
        heavy=settings.heavy_rate_limit_per_minute
        if heavy_rate_limit_per_minute is None
        else heavy_rate_limit_per_minute,
        store=lambda: app.state.kv,
        trusted_proxy_hops=settings.trusted_proxy_hops
        if trusted_proxy_hops is None
        else trusted_proxy_hops,
    )
    origins = get_settings().cors_origins if cors_origins is None else cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            # a failed question that was saved: the app shows "try again" in its conversation
            expose_headers=["X-Conversation-Id"],
        )
    app.include_router(health.router)
    app.include_router(features.router)
    app.include_router(observability.router)
    app.include_router(api_auth.router)
    app.include_router(api_drugs.router)
    app.include_router(api_compare.router)
    app.include_router(api_lasa.router)
    app.include_router(api_me.router)
    app.include_router(api_history.router)
    app.include_router(api_company.router)
    app.include_router(api_operator.router)
    app.include_router(api_pharmacies.router)
    app.include_router(api_pictures.router)
    app.include_router(api_shortage.router)
    app.include_router(api_interactions.router)
    app.include_router(api_assistant.router)
    app.include_router(api_conversations.router)
    app.include_router(api_conversations.shared_router)
    app.include_router(api_voice.router)
    app.include_router(api_recognition.router)
    app.include_router(api_shelf.router)
    app.include_router(api_sources.router)
    app.include_router(api_jobs.router)
    if settings.web_dir:
        mount_web_app(app, Path(settings.web_dir))
    return app
