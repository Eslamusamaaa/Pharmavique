"""PostgreSQL store over the `assistant` schema, under row-level security.

Every per-person call runs in one transaction that first says who is asking (`app.user_id`), so the
policies in `assistant_0001` keep it to that person's rows even if a query here forgot its
`WHERE user_id`. Only reading a share link by its token sets `app.system`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.history import (
    Conversation,
    Message,
    MessageRole,
    MessageStatus,
    SharedCopy,
    TitleSource,
    search_key,
)

_SET_USER = text("SELECT set_config('app.user_id', :user_id, true)")
_SET_SYSTEM = text("SELECT set_config('app.system', 'on', true)")
_COLUMNS = (
    "id, level, title, title_source, pinned, created_at, updated_at, questions, share_token, "
    "shared_at"
)


def _like(key: str) -> str:
    escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _conversation(row: Row[Any]) -> Conversation:
    return Conversation(
        id=row.id,
        level=Level(row.level),
        title=row.title,
        title_source=TitleSource(row.title_source),
        pinned=row.pinned,
        created_at=row.created_at,
        updated_at=row.updated_at,
        questions=row.questions,
        share_token=row.share_token,
        shared_at=row.shared_at,
    )


def _message(row: Row[Any]) -> Message:
    return Message(
        id=row.id,
        role=MessageRole(row.role),
        text=row.text,
        status=MessageStatus(row.status),
        created_at=row.created_at,
        payload=dict(row.payload or {}),
    )


def _copy_json(copy: SharedCopy) -> str:
    return json.dumps(
        {
            "title": copy.title,
            "level": copy.level.value,
            "shared_at": copy.shared_at.isoformat(),
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role.value,
                    "text": m.text,
                    "status": m.status.value,
                    "created_at": m.created_at.isoformat(),
                    "payload": m.payload,
                }
                for m in copy.messages
            ],
        },
        ensure_ascii=False,
    )


def _copy(data: dict[str, Any]) -> SharedCopy:
    return SharedCopy(
        title=data["title"],
        level=Level(data["level"]),
        shared_at=datetime.fromisoformat(data["shared_at"]),
        messages=tuple(
            Message(
                id=UUID(m["id"]),
                role=MessageRole(m["role"]),
                text=m["text"],
                status=MessageStatus(m["status"]),
                created_at=datetime.fromisoformat(m["created_at"]),
                payload=dict(m.get("payload") or {}),
            )
            for m in data["messages"]
        ),
    )


class PostgresConversationStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _as_user(self, user_id: UUID) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session, session.begin():
            await session.execute(_SET_USER, {"user_id": str(user_id)})
            yield session

    @asynccontextmanager
    async def _as_system(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session, session.begin():
            await session.execute(_SET_SYSTEM)
            yield session

    async def create(self, user_id: UUID, conversation: Conversation) -> None:
        async with self._as_user(user_id) as session:
            await session.execute(
                text(
                    "INSERT INTO assistant.conversations (id, user_id, level, title, title_key, "
                    "title_source, pinned, questions, created_at, updated_at) "
                    "VALUES (:id, :u, :level, :title, :key, :source, :pinned, :q, :c, :c)"
                ),
                {
                    "id": conversation.id,
                    "u": user_id,
                    "level": conversation.level.value,
                    "title": conversation.title,
                    "key": search_key(conversation.title),
                    "source": conversation.title_source.value,
                    "pinned": conversation.pinned,
                    "q": conversation.questions,
                    "c": conversation.created_at,
                },
            )

    async def get(self, user_id: UUID, conversation_id: UUID) -> Conversation | None:
        async with self._as_user(user_id) as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM assistant.conversations "  # noqa: S608
                        "WHERE id = :id AND user_id = :u"
                    ),
                    {"id": conversation_id, "u": user_id},
                )
            ).first()
        return _conversation(row) if row else None

    async def messages(
        self, user_id: UUID, conversation_id: UUID, last: int | None = None
    ) -> list[Message]:
        query = (
            "SELECT id, role, text, status, created_at, payload FROM assistant.messages "
            "WHERE conversation_id = :c AND user_id = :u ORDER BY position DESC"
        )
        params: dict[str, Any] = {"c": conversation_id, "u": user_id}
        if last is not None:
            query += " LIMIT :last"
            params["last"] = last
        async with self._as_user(user_id) as session:
            rows = (await session.execute(text(query), params)).all()
        return [_message(r) for r in reversed(rows)]

    async def add_message(
        self, user_id: UUID, conversation_id: UUID, message: Message, at: datetime
    ) -> None:
        async with self._as_user(user_id) as session:
            await session.execute(
                text(
                    "INSERT INTO assistant.messages (id, conversation_id, user_id, role, text, "
                    "text_key, status, payload, created_at) "
                    "VALUES (:id, :c, :u, :role, :text, :key, :status, CAST(:payload AS jsonb), "
                    ":at)"
                ),
                {
                    "id": message.id,
                    "c": conversation_id,
                    "u": user_id,
                    "role": message.role.value,
                    "text": message.text,
                    "key": search_key(message.text),
                    "status": message.status.value,
                    "payload": json.dumps(message.payload, ensure_ascii=False),
                    "at": message.created_at,
                },
            )
            await session.execute(
                text(
                    "UPDATE assistant.conversations SET updated_at = :at, "
                    "questions = questions + :q WHERE id = :c AND user_id = :u"
                ),
                {
                    "at": at,
                    "q": 1 if message.role is MessageRole.USER else 0,
                    "c": conversation_id,
                    "u": user_id,
                },
            )

    async def set_message(
        self, user_id: UUID, message_id: UUID, status: MessageStatus, at: datetime
    ) -> None:
        async with self._as_user(user_id) as session:
            await session.execute(
                text(
                    "WITH changed AS (UPDATE assistant.messages SET status = :s "
                    "WHERE id = :id AND user_id = :u RETURNING conversation_id) "
                    "UPDATE assistant.conversations SET updated_at = :at "
                    "WHERE id IN (SELECT conversation_id FROM changed) AND user_id = :u"
                ),
                {"s": status.value, "id": message_id, "u": user_id, "at": at},
            )

    async def find(self, user_id: UUID, level: Level, query_key: str | None) -> list[Conversation]:
        query = (
            f"SELECT {_COLUMNS} FROM assistant.conversations c "  # noqa: S608
            "WHERE c.user_id = :u AND c.level = :level"
        )
        params: dict[str, Any] = {"u": user_id, "level": level.value}
        if query_key:
            query += (
                " AND (c.title_key LIKE :q ESCAPE '\\' OR EXISTS (SELECT 1 FROM "
                "assistant.messages m WHERE m.conversation_id = c.id AND m.user_id = :u "
                "AND m.text_key LIKE :q ESCAPE '\\'))"
            )
            params["q"] = _like(query_key)
        query += " ORDER BY c.pinned DESC, c.updated_at DESC"
        async with self._as_user(user_id) as session:
            rows = (await session.execute(text(query), params)).all()
        return [_conversation(r) for r in rows]

    async def count(self, user_id: UUID, level: Level) -> int:
        return await self._count(user_id, level, pinned_only=False)

    async def pinned_count(self, user_id: UUID, level: Level) -> int:
        return await self._count(user_id, level, pinned_only=True)

    async def _count(self, user_id: UUID, level: Level, *, pinned_only: bool) -> int:
        query = "SELECT count(*) FROM assistant.conversations WHERE user_id = :u AND level = :l"
        if pinned_only:
            query += " AND pinned"
        async with self._as_user(user_id) as session:
            result = await session.execute(text(query), {"u": user_id, "l": level.value})
            return int(result.scalar_one())

    async def oldest_unpinned(self, user_id: UUID, level: Level) -> UUID | None:
        async with self._as_user(user_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id FROM assistant.conversations WHERE user_id = :u "
                        "AND level = :l AND NOT pinned ORDER BY updated_at LIMIT 1"
                    ),
                    {"u": user_id, "l": level.value},
                )
            ).first()
        return row.id if row else None

    async def update(self, user_id: UUID, conversation: Conversation) -> None:
        async with self._as_user(user_id) as session:
            await session.execute(
                text(
                    "UPDATE assistant.conversations SET title = :title, title_key = :key, "
                    "title_source = :source, pinned = :pinned WHERE id = :id AND user_id = :u"
                ),
                {
                    "title": conversation.title,
                    "key": search_key(conversation.title),
                    "source": conversation.title_source.value,
                    "pinned": conversation.pinned,
                    "id": conversation.id,
                    "u": user_id,
                },
            )

    async def save_share(
        self, user_id: UUID, conversation_id: UUID, token: str, copy: SharedCopy
    ) -> None:
        async with self._as_user(user_id) as session:
            await session.execute(
                text(
                    "UPDATE assistant.conversations SET share_token = :t, shared_at = :at, "
                    "shared_copy = CAST(:copy AS jsonb) WHERE id = :id AND user_id = :u"
                ),
                {
                    "t": token,
                    "at": copy.shared_at,
                    "copy": _copy_json(copy),
                    "id": conversation_id,
                    "u": user_id,
                },
            )

    async def drop_share(self, user_id: UUID, conversation_id: UUID) -> None:
        async with self._as_user(user_id) as session:
            await session.execute(
                text(
                    "UPDATE assistant.conversations SET share_token = NULL, shared_at = NULL, "
                    "shared_copy = NULL WHERE id = :id AND user_id = :u"
                ),
                {"id": conversation_id, "u": user_id},
            )

    async def shared(self, token: str) -> SharedCopy | None:
        async with self._as_system() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT shared_copy FROM assistant.conversations "
                        "WHERE share_token = :t AND shared_copy IS NOT NULL"
                    ),
                    {"t": token},
                )
            ).first()
        return _copy(row.shared_copy) if row else None

    async def delete(self, user_id: UUID, conversation_id: UUID) -> bool:
        async with self._as_user(user_id) as session:
            result = await session.execute(
                text(
                    "DELETE FROM assistant.conversations WHERE id = :id AND user_id = :u "
                    "RETURNING id"
                ),
                {"id": conversation_id, "u": user_id},
            )
            return result.first() is not None

    async def delete_all(self, user_id: UUID, level: Level) -> int:
        async with self._as_user(user_id) as session:
            result = await session.execute(
                text(
                    "DELETE FROM assistant.conversations WHERE user_id = :u AND level = :l "
                    "RETURNING id"
                ),
                {"u": user_id, "l": level.value},
            )
            return len(result.all())

    async def forget(self, user_id: UUID) -> None:
        async with self._as_user(user_id) as session:
            await session.execute(
                text("DELETE FROM assistant.conversations WHERE user_id = :u"), {"u": user_id}
            )
