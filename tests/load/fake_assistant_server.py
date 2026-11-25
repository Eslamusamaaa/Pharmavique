"""The real API with a fake assistant model, for load tests that must not spend a free quota.

Everything else is the real application (search, drug pages, accounts, rate limit, cache) wired from
the environment as usual; only the assistant's language model is replaced by a runner that answers
after a short delay with a canned, cited answer. So a load test of "search and the assistant"
measures the API, the database and the queueing, and never calls Groq, OpenRouter or Cloudflare.

    $env:PHARMAVIQUE_RATE_LIMIT_PER_MINUTE = "0"; $env:PHARMAVIQUE_HEAVY_RATE_LIMIT_PER_MINUTE = "0"
    uv run --group load uvicorn --app-dir tests/load fake_assistant_server:app --port 8010
"""

import asyncio
import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AgentRun
from pharmavique.assistant.domain.answers import Citation, Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.bootstrap.api import create_app

# how long the fake model "thinks"; a real free model takes seconds (docs/PERFORMANCE.md)
DELAY_SECONDS = float(os.environ.get("FAKE_ASSISTANT_DELAY", "0.25"))

CITATION = Citation(
    "catalog:load-test",
    "سجل الأدوية (SFDA)",
    "https://www.sfda.gov.sa/en/drugs-list",
    "catalog",
    None,
)


class FakeRunner:
    """Answers every question with the same cited text after `delay` seconds."""

    def __init__(self, delay: float = DELAY_SECONDS) -> None:
        self._delay = delay
        self.calls = 0

    async def run(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
    ) -> AgentRun:
        self.calls += 1
        await asyncio.sleep(self._delay)
        return AgentRun(
            "هذه إجابة تجريبية للاختبار فقط [1].",
            (CITATION,),
            ("drug_details",),
            model="fake-load-test-model",
        )


def build_app() -> FastAPI:
    app = create_app()
    started = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(inner: FastAPI) -> AsyncIterator[None]:
        async with started(inner):
            # the real wiring has finished: swap only the model
            inner.state.assistant = AskAssistant(FakeRunner())
            yield

    app.router.lifespan_context = lifespan
    return app


app = build_app()
