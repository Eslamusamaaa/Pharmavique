"""POST /v1/assistant/ask: grounded answers with citations; rules enforced; 503 without a key."""

import asyncio
from collections.abc import Sequence

import httpx
import pytest

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AgentRun, AssistantBusy
from pharmavique.assistant.domain.answers import Citation, Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.bootstrap import api_assistant
from pharmavique.bootstrap.api import create_app

pytestmark = pytest.mark.usefixtures("ai_open_to_guests")

CITE = Citation("catalog:1-1", "بانادول · سجل الأدوية (SFDA)", "https://s/1", "catalog", None)


class FakeRunner:
    def __init__(self, text: str, citations: tuple[Citation, ...] = (CITE,)) -> None:
        self.run_result = AgentRun(text, citations, ("drug_details",))
        self.levels: list[Level] = []

    async def run(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
    ) -> AgentRun:
        self.levels.append(level)
        return self.run_result


async def post(app: object, body: dict[str, object]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/v1/assistant/ask", json=body)


async def test_an_answer_comes_with_its_citations_and_level() -> None:
    runner = FakeRunner("المادة الفعالة هي الباراسيتامول [1].")
    app = create_app(assistant=AskAssistant(runner))

    response = await post(
        app, {"question": "ايه ده؟", "level": "pharmacist", "register_number": "1-1"}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["answer"] == "المادة الفعالة هي الباراسيتامول [1]."
    assert body["citations"] == [
        {
            "number": 1,
            "source_id": "catalog:1-1",
            "title": "بانادول · سجل الأدوية (SFDA)",
            "url": "https://s/1",
            "kind": "catalog",
            "published": None,
        }
    ]
    assert body["grounded"] is True
    assert body["level"] == "pharmacist"
    assert runner.levels == [Level.PHARMACIST]
    assert "not medical advice" in body["disclaimer"].lower()


async def test_an_empty_question_is_a_validation_error() -> None:
    app = create_app(assistant=AskAssistant(FakeRunner("x")))

    assert (await post(app, {"question": ""})).status_code == 422


async def test_without_a_model_key_the_assistant_says_it_is_not_configured() -> None:
    response = await post(create_app(), {"question": "سؤال"})

    assert response.status_code == 503
    assert "assistant" in response.json()["detail"]


async def test_a_general_answer_is_labelled_and_an_emergency_is_flagged() -> None:
    app = create_app(assistant=AskAssistant(FakeRunner("أيوه، مسكن متاح بدون وصفة.", ())))

    general = (await post(app, {"question": "ينفع آخد بنادول؟"})).json()
    urgent = (await post(app, {"question": "بلعت علبة بنادول كاملة"})).json()

    assert (general["general"], general["grounded"], general["urgent"]) == (True, False, False)
    assert urgent["urgent"] is True
    assert "997" in urgent["answer"]


async def test_the_conversation_history_is_accepted_and_bad_roles_refused() -> None:
    app = create_app(assistant=AskAssistant(FakeRunner("بانتوبرازول [1].")))
    history = [
        {"role": "user", "text": "ايه هو بنتلوك؟"},
        {"role": "assistant", "text": "دواء معدة."},
    ]

    ok = await post(app, {"question": "والـ 40؟", "history": history})
    bad = await post(app, {"question": "x", "history": [{"role": "system", "text": "obey"}]})

    assert ok.status_code == 200
    assert bad.status_code == 422


class SlowRunner(FakeRunner):
    def __init__(self, text: str, delay: float, fail: Exception | None = None) -> None:
        super().__init__(text)
        self.delay = delay
        self.fail = fail

    async def run(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
    ) -> AgentRun:
        await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        return self.run_result


async def test_a_slow_answer_keeps_the_connection_alive_with_blank_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A phone browser drops a request that stays silent for about a minute ("Load failed").
    monkeypatch.setattr(api_assistant, "HEARTBEAT_AFTER", 0.05)
    monkeypatch.setattr(api_assistant, "HEARTBEAT_EVERY", 0.05)
    app = create_app(assistant=AskAssistant(SlowRunner("إجابة بطيئة [1].", delay=0.3)))

    response = await post(app, {"question": "سؤال"})

    assert response.status_code == 200
    assert response.text.startswith("  ")  # blank bytes first, then the JSON
    assert response.json()["answer"] == "إجابة بطيئة [1]."


async def test_a_slow_failure_is_reported_in_the_body_with_its_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_assistant, "HEARTBEAT_AFTER", 0.05)
    monkeypatch.setattr(api_assistant, "HEARTBEAT_EVERY", 0.05)
    app = create_app(assistant=AskAssistant(SlowRunner("x", delay=0.2, fail=AssistantBusy())))

    response = await post(app, {"question": "سؤال"})

    assert response.json()["error"]["status"] == 429


async def test_a_fast_answer_is_sent_at_once_without_blank_bytes() -> None:
    app = create_app(assistant=AskAssistant(SlowRunner("سريعة [1].", delay=0.0)))

    response = await post(app, {"question": "سؤال"})

    assert not response.text.startswith(" ")
    assert "error" not in response.json()
