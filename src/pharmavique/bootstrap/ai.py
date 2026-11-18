"""Wiring of the AI adapters from settings (ADR-005): which provider, model and key go where.

Every builder returns None when its key is missing, so the API still starts and only that feature
answers 503. Keys never leave this module except in the provider's own Authorization header.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.infrastructure.langgraph_agent import LangGraphAgentRunner
from pharmavique.bootstrap.assistant_facts import ContractDrugFacts
from pharmavique.bootstrap.settings import Settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.knowledge.application.retrieve import RetrievePassages
from pharmavique.knowledge.infrastructure.openai_embedder import OpenAICompatibleEmbedder
from pharmavique.knowledge.infrastructure.postgres import PostgresPassageSearch
from pharmavique.search.contracts.queries import ProductSearch
from pharmavique.substitution.contracts.queries import EquivalenceQueries

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
        max_retries=1,
    )


def build_assistant(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    search: ProductSearch,
    catalog: ReadProductCardsHandler,
    equivalence: EquivalenceQueries,
) -> AskAssistant | None:
    model = build_chat_model(settings)
    if model is None:
        return None
    passages = RetrievePassages(PostgresPassageSearch(session_factory), build_embedder(settings))
    facts = ContractDrugFacts(search, catalog, catalog, equivalence, passages)
    return AskAssistant(LangGraphAgentRunner(model, facts))
