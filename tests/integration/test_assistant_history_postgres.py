"""Saved conversations against a real Postgres, as an ordinary role so row-level security applies
(the development user is a superuser and would skip it)."""

import asyncio
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from pharmavique.assistant.application.history import ConversationService
from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.history import (
    MAX_CONVERSATIONS,
    ConversationNotFound,
    MessageStatus,
)
from pharmavique.assistant.infrastructure.postgres_history import PostgresConversationStore
from pharmavique.foundation.db.engine import create_engine, create_session_factory

pytestmark = pytest.mark.integration

ROLE = "pv_rls_assistant_test"


class TickingClock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        self.at += timedelta(seconds=1)
        return self.at


@pytest.fixture
async def limited(
    migrated_url: URL, engine: AsyncEngine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    password = secrets.token_hex(16)
    async with engine.begin() as connection:
        exists = await connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}
        )
        if exists.first() is not None:
            await connection.execute(text(f"DROP OWNED BY {ROLE}"))
        await connection.execute(text(f"DROP ROLE IF EXISTS {ROLE}"))
        await connection.execute(
            text(f"CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'")
        )
        await connection.execute(text(f"GRANT USAGE ON SCHEMA assistant TO {ROLE}"))
        await connection.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA assistant TO {ROLE}"
            )
        )
        await connection.execute(text("TRUNCATE assistant.conversations CASCADE"))
    url = migrated_url.set(username=ROLE, password=password)
    limited_engine = create_engine(url.render_as_string(hide_password=False))
    yield create_session_factory(limited_engine)
    await limited_engine.dispose()


def service(factory: async_sessionmaker[AsyncSession]) -> ConversationService:
    return ConversationService(PostgresConversationStore(factory), TickingClock())


async def test_a_conversation_is_saved_reopened_and_continued(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    svc, me = service(limited), uuid4()
    first = await svc.begin(me, None, Level.PATIENT, "بنادول 500؟")
    payload = {"citations": [{"number": 1, "title": "سجل الهيئة"}], "history_check": {"x": "ي"}}
    await svc.answered(me, first, "قرص باراسيتامول [1]", payload)
    follow = await svc.begin(me, first.conversation.id, Level.PATIENT, "وال 1000؟")
    await svc.failed(me, follow)

    conversation, messages = await svc.open(me, first.conversation.id)

    assert conversation.questions == 2
    assert [(m.role.value, m.status) for m in messages] == [
        ("user", MessageStatus.OK),
        ("assistant", MessageStatus.OK),
        ("user", MessageStatus.FAILED),
    ]
    assert messages[1].payload == payload
    assert [t.text for t in follow.history] == ["بنادول 500؟", "قرص باراسيتامول [1]"]

    again = await svc.begin(me, first.conversation.id, Level.PATIENT, "وال 1000؟")
    assert again.question_id == follow.question_id


async def test_search_list_order_pin_and_the_cap(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    svc, me = service(limited), uuid4()
    first = await svc.begin(me, None, Level.PATIENT, "سؤال عن الأسبرين")
    await svc.answered(me, first, "جواب 50% من الحالات_", {})
    await svc.pin(me, first.conversation.id, True)
    for i in range(MAX_CONVERSATIONS):
        pending = await svc.begin(me, None, Level.PATIENT, f"سؤال {i}")
        await svc.answered(me, pending, "جواب", {})

    found, total = await svc.conversations(me, Level.PATIENT)
    assert total == MAX_CONVERSATIONS
    assert found[0].id == first.conversation.id
    assert found[1].title == f"سؤال {MAX_CONVERSATIONS - 1}"
    assert "سؤال 0" not in [c.title for c in found]  # the oldest unpinned made room

    assert [c.title for c in (await svc.conversations(me, Level.PATIENT, "اسبرين"))[0]] == [
        "سؤال عن الأسبرين"
    ]
    assert len((await svc.conversations(me, Level.PATIENT, "50"))[0]) == 1  # found in the answer
    # punctuation alone normalizes to nothing: the whole list, not an error
    assert len((await svc.conversations(me, Level.PATIENT, "%_"))[0]) == MAX_CONVERSATIONS


async def test_the_database_hides_other_peoples_conversations(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    svc, a, b = service(limited), uuid4(), uuid4()
    pending = await svc.begin(a, None, Level.PATIENT, "سؤال أ")
    await svc.answered(a, pending, "جواب", {})

    with pytest.raises(ConversationNotFound):
        await svc.open(b, pending.conversation.id)
    async with limited() as session, session.begin():
        await session.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(b)})
        seen = (await session.execute(text("SELECT id FROM assistant.messages"))).all()
    async with limited() as session, session.begin():
        nobody = (await session.execute(text("SELECT id FROM assistant.conversations"))).all()

    assert seen == []  # a forgotten WHERE still shows b nothing of a's
    assert nobody == []  # no identity set: fails closed


async def test_a_share_link_reads_without_an_identity_and_dies_with_the_conversation(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    svc, me = service(limited), uuid4()
    pending = await svc.begin(me, None, Level.PHARMACIST, "سؤال")
    await svc.answered(me, pending, "جواب", {"history_check": {"medicines": ["بنادول"]}})
    token = await svc.share(me, pending.conversation.id)

    copy = await svc.shared(token)
    assert copy.level is Level.PHARMACIST
    assert copy.messages[1].payload == {"history_check": {"medicines": ["بنادول"]}}

    await svc.delete(me, pending.conversation.id)
    with pytest.raises(ConversationNotFound):
        await svc.shared(token)
    async with limited() as session, session.begin():
        await session.execute(text("SELECT set_config('app.system', 'on', true)"))
        left = (await session.execute(text("SELECT id FROM assistant.messages"))).all()
    assert left == []  # the messages went with the conversation


async def test_forget_deletes_everything_of_the_person(
    limited: async_sessionmaker[AsyncSession],
) -> None:
    svc, me, other = service(limited), uuid4(), uuid4()
    await svc.begin(me, None, Level.PATIENT, "سؤال")
    await svc.begin(me, None, Level.CLINICAL, "سؤال")
    await svc.begin(other, None, Level.PATIENT, "سؤال")

    await svc.forget(me)

    assert (await svc.conversations(me, Level.PATIENT))[1] == 0
    assert (await svc.conversations(me, Level.CLINICAL))[1] == 0
    assert (await svc.conversations(other, Level.PATIENT))[1] == 1


async def test_the_assistant_migration_is_reversible(
    migrated_url: URL, make_alembic_config: object
) -> None:
    config = make_alembic_config(migrated_url)  # type: ignore[operator]
    await asyncio.to_thread(command.downgrade, config, "assistant@base")
    await asyncio.to_thread(command.upgrade, config, "assistant@head")
