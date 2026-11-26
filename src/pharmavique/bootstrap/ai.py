"""Wiring of the AI adapters from settings (ADR-005): which provider, model and key go where.

Every builder returns None when its key is missing, so the API still starts and only that feature
answers 503. Keys never leave this module except in the provider's own Authorization header.

LangChain, LangGraph and the OpenAI client take about 1.7 s to import, most of a cold start on
Vercel. They are imported on the first question (`_LazyAgentRunner`, `_LazyNameExtractor`), never
at startup, so a search or a drug page on a fresh instance does not wait for them.
"""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import (
    AgentRun,
    AgentRunner,
    AssistantObserver,
    SfdaSiteLookup,
)
from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.assistant.infrastructure.prompt_guard import GroqPromptGuard
from pharmavique.assistant.infrastructure.web_search import TavilyWebSearch
from pharmavique.bootstrap.assistant_facts import ContractDrugFacts
from pharmavique.bootstrap.recognition_candidates import SearchCandidateFinder
from pharmavique.bootstrap.settings import Settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.infrastructure.persistence.list_items import SqlAlchemyListItemReader
from pharmavique.interactions.application.check import CheckInteractions
from pharmavique.interactions.application.contraindications import ListContraindications
from pharmavique.interactions.infrastructure.postgres import (
    PostgresContraindicationStore,
    PostgresInteractionStore,
)
from pharmavique.knowledge.application.retrieve import RetrievePassages
from pharmavique.knowledge.infrastructure.openai_embedder import (
    FallbackEmbedder,
    OpenAICompatibleEmbedder,
)
from pharmavique.knowledge.infrastructure.postgres import PostgresPassageSearch
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.recognition.infrastructure.openai_vision import (
    FallbackVisionReader,
    OpenAICompatibleVisionReader,
)
from pharmavique.search.contracts.queries import ProductSearch
from pharmavique.substitution.contracts.queries import EquivalenceQueries
from pharmavique.voice.application.ports import DrugNameExtractor, SpeechToText, TextToSpeech
from pharmavique.voice.application.speak import Speak, Transcribe
from pharmavique.voice.infrastructure.cloudflare_speech import CloudflareSpeechToText
from pharmavique.voice.infrastructure.elevenlabs_speech import ElevenLabsTextToSpeech
from pharmavique.voice.infrastructure.groq_speech import GroqSpeechToText, GroqTextToSpeech

if TYPE_CHECKING:
    from pharmavique.voice.infrastructure.llm_name import LlmDrugNameExtractor

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_embedder(settings: Settings) -> FallbackEmbedder | None:
    """bge-m3 on Cloudflare when it is configured (free, and its vectors are identical to the ones
    OpenRouter made: cosine 1.0 on six stored chunks), with OpenRouter as its backup. The label
    stored with the vectors stays `embedding_model` either way, so nothing is re-embedded."""
    embedders: list[OpenAICompatibleEmbedder] = []
    cloudflare_url = settings.cloudflare_base_url
    if cloudflare_url is not None and settings.cloudflare_api_token is not None:
        embedders.append(
            OpenAICompatibleEmbedder(
                cloudflare_url,
                settings.cloudflare_api_token.get_secret_value(),
                settings.embedding_model,
                settings.embedding_dimensions,
                api_model=settings.cloudflare_embedding_model,
                send_dimensions=False,
            )
        )
    if settings.openrouter_api_key is not None:
        embedders.append(
            OpenAICompatibleEmbedder(
                settings.embedding_base_url,
                settings.openrouter_api_key.get_secret_value(),
                settings.embedding_model,
                settings.embedding_dimensions,
            )
        )
    return FallbackEmbedder(embedders) if embedders else None


def has_chat_model(settings: Settings) -> bool:
    """Whether `build_chat_model` would build a model, without importing LangChain."""
    first = (
        settings.groq_api_key if settings.llm_provider == "groq" else settings.openrouter_api_key
    )
    return (
        first is not None
        or settings.cloudflare_base_url is not None
        or (settings.openrouter_api_key is not None and bool(settings.llm_backup_models))
    )


def build_chat_model(settings: Settings) -> Any | None:
    """A LangChain chat model with tool calling, over an OpenAI-compatible endpoint.

    Every free model that has a key is in the chain, in order: Groq (or OpenRouter), then Gemma on
    Cloudflare, then the free OpenRouter models of `llm_backup_models`. Groq's free plan allows
    8,000 tokens a minute, about one answer, so the backups carry the rest.
    """
    from langchain_openai import ChatOpenAI  # imported here: only the API process needs it

    from pharmavique.assistant.infrastructure.cloudflare_chat import CloudflareChatOpenAI
    from pharmavique.assistant.infrastructure.fallback_model import FallbackChatModel

    if settings.llm_provider == "groq":
        key, base_url = settings.groq_api_key, GROQ_BASE_URL
    else:
        key, base_url = settings.openrouter_api_key, OPENROUTER_BASE_URL
    models: list[Any] = []
    if key is not None:
        models.append(
            ChatOpenAI(
                model=settings.llm_model,
                base_url=base_url,
                api_key=key,
                temperature=0,
                timeout=60,
                max_retries=0,  # hand over to the backup at once
            )
        )
        backup = settings.groq_backup_model
        if settings.llm_provider == "groq" and backup and backup != settings.llm_model:
            models.append(
                ChatOpenAI(
                    model=backup,
                    base_url=base_url,
                    api_key=key,
                    temperature=0,
                    timeout=60,
                    max_retries=0,
                )
            )
    cloudflare_url = settings.cloudflare_base_url
    if cloudflare_url is not None:
        models.append(
            CloudflareChatOpenAI(
                model=settings.cloudflare_llm_model,
                base_url=cloudflare_url,
                api_key=settings.cloudflare_api_token,
                temperature=0,
                timeout=60,
                max_retries=0,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": settings.cloudflare_llm_thinking}
                },
            )
        )
    if settings.openrouter_api_key is not None:
        models.extend(
            ChatOpenAI(
                model=name,
                base_url=OPENROUTER_BASE_URL,
                api_key=settings.openrouter_api_key,
                temperature=0,
                timeout=60,
                max_retries=0,
            )
            for name in settings.llm_backup_models
            if name != settings.llm_model
        )
    if not models:
        return None
    if len(models) == 1:
        alone: Any = models[0]
        alone.max_retries = 4  # alone, wait out short limits instead of failing
        return alone
    return FallbackChatModel(*models)


class _LazyNameExtractor:
    """Implements `DrugNameExtractor`: the model is built (and LangChain imported) on first use."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._inner: LlmDrugNameExtractor | None = None

    async def extract(self, text: str) -> str | None:
        if self._inner is None:
            from pharmavique.voice.infrastructure.llm_name import LlmDrugNameExtractor

            self._inner = LlmDrugNameExtractor(build_chat_model(self._settings))
        return await self._inner.extract(text)


class _LazyTitleWriter:
    """Implements `TitleWriter`: the chat model is built (and LangChain imported) on first use."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._inner: Any | None = None

    async def title(self, question: str, answer: str) -> str | None:
        if self._inner is None:
            from pharmavique.assistant.infrastructure.title_writer import ModelTitleWriter

            self._inner = ModelTitleWriter(build_chat_model(self._settings))
        result: str | None = await self._inner.title(question, answer)
        return result


def build_title_writer(settings: Settings) -> _LazyTitleWriter | None:
    """The model that names a saved conversation (ADR-022); None without a key."""
    return _LazyTitleWriter(settings) if has_chat_model(settings) else None


def build_name_extractor(settings: Settings) -> DrugNameExtractor | None:
    """The model that picks the drug name out of a spoken request; None without a key."""
    return _LazyNameExtractor(settings) if has_chat_model(settings) else None


def build_tts(settings: Settings) -> list[TextToSpeech]:
    """Every voice that has a key, the chosen provider first: ElevenLabs and Groq's Orpheus Arabic
    Saudi back each other up."""
    elevenlabs: TextToSpeech | None = None
    groq: TextToSpeech | None = None
    if settings.elevenlabs_api_key is not None:
        elevenlabs = ElevenLabsTextToSpeech(
            settings.elevenlabs_api_key.get_secret_value(),
            settings.elevenlabs_voice_id,
            settings.elevenlabs_model,
        )
    if settings.groq_api_key is not None:
        groq = GroqTextToSpeech(
            settings.groq_api_key.get_secret_value(), settings.tts_model, settings.tts_voice
        )
    order = [elevenlabs, groq] if settings.tts_provider == "elevenlabs" else [groq, elevenlabs]
    return [voice for voice in order if voice is not None]


def build_stt(settings: Settings) -> list[SpeechToText]:
    """Whisper on Groq, then the same Whisper on Cloudflare as its free backup."""
    listeners: list[SpeechToText] = []
    if settings.groq_api_key is not None:
        listeners.append(
            GroqSpeechToText(settings.groq_api_key.get_secret_value(), settings.stt_model)
        )
    if settings.cloudflare_api_token is not None and settings.cloudflare_account_id:
        listeners.append(
            CloudflareSpeechToText(
                settings.cloudflare_account_id,
                settings.cloudflare_api_token.get_secret_value(),
                settings.cloudflare_stt_model,
            )
        )
    return listeners


def build_voice(settings: Settings) -> tuple[Transcribe | None, Speak | None]:
    """Listening and the Saudi Arabic voice, each with every free backup that has a key."""
    listeners, voices = build_stt(settings), build_tts(settings)
    return (
        Transcribe(*listeners) if listeners else None,
        Speak(*voices) if voices else None,
    )


def build_scanner(
    settings: Settings, *, search: ProductSearch, catalog: ReadProductCardsHandler
) -> ScanImage | None:
    """The vision readers, tried in order: Cloudflare first when configured (Llama 4 Scout read a
    test picture correctly in 3.5 s for about 12 Neurons), then the free models on OpenRouter."""
    readers: list[OpenAICompatibleVisionReader] = []
    cloudflare_url = settings.cloudflare_base_url
    if cloudflare_url is not None and settings.cloudflare_api_token is not None:
        key = settings.cloudflare_api_token.get_secret_value()
        readers.append(
            OpenAICompatibleVisionReader(cloudflare_url, key, settings.cloudflare_vision_model)
        )
    if settings.openrouter_api_key is not None:
        key = settings.openrouter_api_key.get_secret_value()
        readers.extend(
            OpenAICompatibleVisionReader(OPENROUTER_BASE_URL, key, m)
            for m in settings.vision_models
        )
    if not readers:
        return None
    return ScanImage(
        FallbackVisionReader(readers),
        SearchCandidateFinder(search, catalog),
        min_score=settings.scan_min_score,
    )


def build_assistant(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    search: ProductSearch,
    catalog: ReadProductCardsHandler,
    equivalence: EquivalenceQueries,
    observer: AssistantObserver | None = None,
) -> AskAssistant | None:
    if not has_chat_model(settings):
        return None
    passages = RetrievePassages(PostgresPassageSearch(session_factory), build_embedder(settings))
    interactions = CheckInteractions(PostgresInteractionStore(session_factory))
    facts = ContractDrugFacts(
        search,
        catalog,
        catalog,
        equivalence,
        passages,
        interactions=interactions,
        contraindication_checks=ListContraindications(
            PostgresContraindicationStore(session_factory)
        ),
        list_items=SqlAlchemyListItemReader(session_factory),
    )
    detector = None
    if settings.groq_api_key is not None and settings.prompt_guard_model:
        detector = GroqPromptGuard(
            settings.groq_api_key.get_secret_value(), settings.prompt_guard_model
        )
    web = (
        TavilyWebSearch(settings.tavily_api_key.get_secret_value())
        if settings.tavily_api_key is not None
        else None
    )

    def runner() -> AgentRunner:
        from pharmavique.assistant.infrastructure.langgraph_agent import LangGraphAgentRunner
        from pharmavique.assistant.infrastructure.sfda_site import SfdaSiteSearch

        site: SfdaSiteLookup | None = SfdaSiteSearch() if settings.sfda_site_check else None
        return LangGraphAgentRunner(build_chat_model(settings), facts, web=web, site=site)

    return AskAssistant(_LazyAgentRunner(runner), detector=detector, observer=observer)


class _LazyAgentRunner:
    """Implements `AgentRunner`: the LangGraph runner is built on the first question."""

    def __init__(self, build: Callable[[], AgentRunner]) -> None:
        self._build = build
        self._inner: AgentRunner | None = None

    async def run(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
    ) -> AgentRun:
        if self._inner is None:
            self._inner = self._build()
        return await self._inner.run(
            question, level, register_number, spoken=spoken, history=history
        )
