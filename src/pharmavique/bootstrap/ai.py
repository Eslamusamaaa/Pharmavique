"""Wiring of the AI adapters from settings (ADR-005): which provider, model and key go where.

Every builder returns None when its key is missing, so the API still starts and only that feature
answers 503. Keys never leave this module except in the provider's own Authorization header.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AssistantObserver
from pharmavique.assistant.infrastructure.langgraph_agent import LangGraphAgentRunner
from pharmavique.assistant.infrastructure.prompt_guard import GroqPromptGuard
from pharmavique.bootstrap.assistant_facts import ContractDrugFacts
from pharmavique.bootstrap.recognition_candidates import SearchCandidateFinder
from pharmavique.bootstrap.settings import Settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.knowledge.application.retrieve import RetrievePassages
from pharmavique.knowledge.infrastructure.openai_embedder import OpenAICompatibleEmbedder
from pharmavique.knowledge.infrastructure.postgres import PostgresPassageSearch
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.recognition.infrastructure.openai_vision import (
    FallbackVisionReader,
    OpenAICompatibleVisionReader,
)
from pharmavique.search.contracts.queries import ProductSearch
from pharmavique.substitution.contracts.queries import EquivalenceQueries
from pharmavique.voice.application.ports import TextToSpeech
from pharmavique.voice.application.speak import Speak, Transcribe
from pharmavique.voice.infrastructure.elevenlabs_speech import ElevenLabsTextToSpeech
from pharmavique.voice.infrastructure.groq_speech import GroqSpeechToText, GroqTextToSpeech

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_embedder(settings: Settings) -> OpenAICompatibleEmbedder | None:
    if settings.openrouter_api_key is None:
        return None
    return OpenAICompatibleEmbedder(
        settings.embedding_base_url,
        settings.openrouter_api_key.get_secret_value(),
        settings.embedding_model,
        settings.embedding_dimensions,
    )


def build_chat_model(settings: Settings) -> Any | None:
    """A LangChain chat model with tool calling, over an OpenAI-compatible endpoint."""
    from langchain_openai import ChatOpenAI  # imported here: only the API process needs it

    if settings.llm_provider == "groq":
        key, base_url = settings.groq_api_key, GROQ_BASE_URL
    else:
        key, base_url = settings.openrouter_api_key, OPENROUTER_BASE_URL
    if key is None:
        return None
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=base_url,
        api_key=key,
        temperature=0,
        timeout=60,
        # The free tier allows 8,000 tokens a minute: wait out short limits instead of failing.
        max_retries=4,
    )


def build_tts(settings: Settings) -> TextToSpeech | None:
    if settings.tts_provider == "elevenlabs" and settings.elevenlabs_api_key is not None:
        return ElevenLabsTextToSpeech(
            settings.elevenlabs_api_key.get_secret_value(),
            settings.elevenlabs_voice_id,
            settings.elevenlabs_model,
        )
    if settings.groq_api_key is not None:
        return GroqTextToSpeech(
            settings.groq_api_key.get_secret_value(), settings.tts_model, settings.tts_voice
        )
    return None


def build_voice(settings: Settings) -> tuple[Transcribe | None, Speak | None]:
    """Whisper through Groq for listening; ElevenLabs (or Groq) for the Saudi Arabic voice."""
    transcribe = None
    if settings.groq_api_key is not None:
        transcribe = Transcribe(
            GroqSpeechToText(settings.groq_api_key.get_secret_value(), settings.stt_model)
        )
    tts = build_tts(settings)
    return transcribe, (Speak(tts) if tts is not None else None)


def build_scanner(
    settings: Settings, *, search: ProductSearch, catalog: ReadProductCardsHandler
) -> ScanImage | None:
    """The vision model (through OpenRouter) and the registry search for its candidates."""
    if settings.openrouter_api_key is None:
        return None
    key = settings.openrouter_api_key.get_secret_value()
    reader = FallbackVisionReader(
        [OpenAICompatibleVisionReader(OPENROUTER_BASE_URL, key, m) for m in settings.vision_models]
    )
    return ScanImage(reader, SearchCandidateFinder(search, catalog))


def build_assistant(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    search: ProductSearch,
    catalog: ReadProductCardsHandler,
    equivalence: EquivalenceQueries,
    observer: AssistantObserver | None = None,
) -> AskAssistant | None:
    model = build_chat_model(settings)
    if model is None:
        return None
    passages = RetrievePassages(PostgresPassageSearch(session_factory), build_embedder(settings))
    facts = ContractDrugFacts(search, catalog, catalog, equivalence, passages)
    detector = None
    if settings.groq_api_key is not None and settings.prompt_guard_model:
        detector = GroqPromptGuard(
            settings.groq_api_key.get_secret_value(), settings.prompt_guard_model
        )
    return AskAssistant(LangGraphAgentRunner(model, facts), detector=detector, observer=observer)
