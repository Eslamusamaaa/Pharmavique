"""/v1/assistant/conversations and /v1/shared: the saved conversations of a signed-in person."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from pharmavique.assistant.application.history import ConversationService
from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.history import MAX_PINNED
from pharmavique.assistant.infrastructure.memory_history import MemoryConversationStore
from pharmavique.bootstrap.api import create_app
from pharmavique.bootstrap.features import get_features
from pharmavique.identity.infrastructure.tokens import JwtAccessTokens
from pharmavique.shared_kernel.principal import Principal, Role

TOKENS = JwtAccessTokens("k" * 40)


class TickingClock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        self.at += timedelta(seconds=1)
        return self.at


class FakeTitles:
    def __init__(self, title: str | None) -> None:
        self.reply = title
        self.calls: list[tuple[str, str]] = []

    async def title(self, question: str, answer: str) -> str | None:
        self.calls.append((question, answer))
        return self.reply


class Api:
    def __init__(self, titles: FakeTitles | None = None) -> None:
        self.service = ConversationService(MemoryConversationStore(), TickingClock())
        self.app: FastAPI = create_app(
            token_verifier=TOKENS, conversations=self.service, title_writer=titles
        )

    def person(self, role: Role = Role.PATIENT) -> tuple[UUID, dict[str, str]]:
        user = uuid4()
        token, _ = TOKENS.issue(Principal(user, None, frozenset({role})), datetime.now(UTC))
        return user, {"Authorization": f"Bearer {token}"}

    async def saved(self, user: UUID, question: str, level: Level = Level.PATIENT) -> UUID:
        pending = await self.service.begin(user, None, level, question)
        payload = {"answer": f"جواب {question}", "citations": [{"trust_grade": "official_sa"}]}
        await self.service.answered(user, pending, f"جواب {question}", payload)
        return pending.conversation.id

    async def call(
        self, method: str, path: str, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> httpx.Response:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, headers=headers or {}, **kwargs)


BASE = "/v1/assistant/conversations"


@pytest.fixture
def history_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PHARMAVIQUE_FEATURE_CHAT_HISTORY", "false")
    get_features.cache_clear()
    yield
    get_features.cache_clear()


async def test_my_list_search_and_one_conversation() -> None:
    api = Api()
    me, headers = api.person()
    first = await api.saved(me, "سؤال عن الأسبرين")
    await api.saved(me, "سؤال ثاني")

    listing = (await api.call("GET", BASE, headers)).json()
    found = (await api.call("GET", BASE, headers, params={"q": "اسبرين"})).json()
    detail = (await api.call("GET", f"{BASE}/{first}", headers)).json()

    assert [c["title"] for c in listing["conversations"]] == ["سؤال ثاني", "سؤال عن الأسبرين"]
    assert (listing["level"], listing["total"], listing["limit"], listing["warn_at"]) == (
        "patient",
        2,
        50,
        45,
    )
    assert [c["title"] for c in found["conversations"]] == ["سؤال عن الأسبرين"]
    assert found["total"] == 2
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["answer"] is None
    assert detail["messages"][1]["answer"]["citations"] == [{"trust_grade": "official_sa"}]
    assert "not medical advice" in detail["disclaimer"].lower()


async def test_the_list_follows_the_account_role_and_an_operator_picks() -> None:
    api = Api()
    pharmacist, ph_headers = api.person(Role.PHARMACIST)
    await api.saved(pharmacist, "سؤال صيدلي", Level.PHARMACIST)
    operator, op_headers = api.person(Role.OPERATOR)
    await api.saved(operator, "سؤال تخصصي", Level.CLINICAL)

    asked_patient = (await api.call("GET", BASE, ph_headers, params={"level": "patient"})).json()
    clinical = (await api.call("GET", BASE, op_headers, params={"level": "clinical"})).json()

    assert asked_patient["level"] == "pharmacist"
    assert [c["title"] for c in asked_patient["conversations"]] == ["سؤال صيدلي"]
    assert [c["title"] for c in clinical["conversations"]] == ["سؤال تخصصي"]


async def test_someone_else_cannot_see_or_change_my_conversation() -> None:
    api = Api()
    me, _ = api.person()
    _, other = api.person()
    mine = await api.saved(me, "سؤالي")

    for method, path in (
        ("GET", f"{BASE}/{mine}"),
        ("PATCH", f"{BASE}/{mine}"),
        ("DELETE", f"{BASE}/{mine}"),
        ("POST", f"{BASE}/{mine}/share"),
        ("POST", f"{BASE}/{mine}/title"),
    ):
        kwargs = {"json": {"title": "x"}} if method == "PATCH" else {}
        assert (await api.call(method, path, other, **kwargs)).status_code == 404, path
    assert (await api.call("GET", BASE, other)).json()["conversations"] == []


async def test_rename_pin_and_their_limits() -> None:
    api = Api()
    me, headers = api.person()
    ids = [await api.saved(me, f"سؤال {i}") for i in range(MAX_PINNED + 1)]

    renamed = await api.call("PATCH", f"{BASE}/{ids[0]}", headers, json={"title": " اسم جديد "})
    empty = await api.call("PATCH", f"{BASE}/{ids[0]}", headers, json={"title": "   "})
    for conversation_id in ids[:MAX_PINNED]:
        await api.call("PATCH", f"{BASE}/{conversation_id}", headers, json={"pinned": True})
    too_many = await api.call("PATCH", f"{BASE}/{ids[-1]}", headers, json={"pinned": True})

    assert renamed.json()["title"] == "اسم جديد"
    assert empty.status_code == 422
    assert too_many.status_code == 409
    listing = (await api.call("GET", BASE, headers)).json()["conversations"]
    assert [c["pinned"] for c in listing] == [True] * MAX_PINNED + [False]


async def test_delete_one_and_delete_all() -> None:
    api = Api()
    me, headers = api.person()
    first = await api.saved(me, "واحد")
    await api.saved(me, "اثنين")
    await api.saved(me, "ثلاثة")

    assert (await api.call("DELETE", f"{BASE}/{first}", headers)).status_code == 204
    assert (await api.call("GET", f"{BASE}/{first}", headers)).status_code == 404
    assert (await api.call("DELETE", BASE, headers)).json() == {"deleted": 2}
    assert (await api.call("GET", BASE, headers)).json()["total"] == 0


async def test_the_model_names_the_conversation_once() -> None:
    titles = FakeTitles("مقارنة بنادول")
    api = Api(titles)
    me, headers = api.person()
    conversation = await api.saved(me, "وش الفرق بين بنادول وبنادول اكسترا؟")

    first = (await api.call("POST", f"{BASE}/{conversation}/title", headers)).json()
    titles.reply = "عنوان ثاني"
    second = (await api.call("POST", f"{BASE}/{conversation}/title", headers)).json()

    assert first["title"] == second["title"] == "مقارنة بنادول"
    assert titles.calls == [
        ("وش الفرق بين بنادول وبنادول اكسترا؟", "جواب وش الفرق بين بنادول وبنادول اكسترا؟")
    ]


async def test_without_a_title_model_the_question_title_stays() -> None:
    api = Api(FakeTitles(None))
    me, headers = api.person()
    conversation = await api.saved(me, "سؤال")

    assert (await api.call("POST", f"{BASE}/{conversation}/title", headers)).json()["title"] == (
        "سؤال"
    )


async def test_a_shared_copy_opens_without_an_account_until_the_link_is_revoked() -> None:
    api = Api()
    me, headers = api.person()
    conversation = await api.saved(me, "سؤال")

    shared = (await api.call("POST", f"{BASE}/{conversation}/share", headers)).json()
    public = await api.call("GET", f"/v1/shared/{shared['token']}")
    listed = (await api.call("GET", BASE, headers)).json()["conversations"][0]

    assert shared["path"] == f"/shared/{shared['token']}"
    assert public.status_code == 200
    assert public.headers["x-robots-tag"] == "noindex, nofollow"
    assert [m["text"] for m in public.json()["messages"]] == ["سؤال", "جواب سؤال"]
    assert (listed["shared"], listed["share_token"]) == (True, shared["token"])

    assert (await api.call("DELETE", f"{BASE}/{conversation}/share", headers)).status_code == 204
    assert (await api.call("GET", f"/v1/shared/{shared['token']}")).status_code == 404
    assert (await api.call("GET", f"/v1/shared/{'x' * 100}")).status_code == 404


async def test_the_routes_need_an_account() -> None:
    api = Api()

    assert (await api.call("GET", BASE)).status_code == 401


@pytest.mark.usefixtures("history_off")
async def test_the_routes_are_hidden_with_the_flag_off() -> None:
    api = Api()
    me, headers = api.person()
    conversation = await api.saved(me, "سؤال")
    token = await api.service.share(me, conversation)

    assert (await api.call("GET", BASE, headers)).status_code == 404
    assert (await api.call("GET", f"/v1/shared/{token}")).status_code == 404
