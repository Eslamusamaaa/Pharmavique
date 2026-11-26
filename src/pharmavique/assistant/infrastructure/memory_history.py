"""Conversations kept in memory: for tests and for one process without a database. The rules live in
`ConversationService`; this only stores, filters and sorts like the Postgres store does."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.history import (
    Conversation,
    Message,
    MessageRole,
    MessageStatus,
    SharedCopy,
    search_key,
)


@dataclass
class _Row:
    user_id: UUID
    conversation: Conversation
    messages: list[Message] = field(default_factory=list)
    shared: SharedCopy | None = None


class MemoryConversationStore:
    def __init__(self) -> None:
        self._rows: dict[UUID, _Row] = {}

    def _mine(self, user_id: UUID, conversation_id: UUID) -> _Row | None:
        row = self._rows.get(conversation_id)
        return row if row is not None and row.user_id == user_id else None

    def _list(self, user_id: UUID, level: Level) -> list[_Row]:
        return [
            r for r in self._rows.values() if r.user_id == user_id and r.conversation.level == level
        ]

    async def create(self, user_id: UUID, conversation: Conversation) -> None:
        self._rows[conversation.id] = _Row(user_id, conversation)

    async def get(self, user_id: UUID, conversation_id: UUID) -> Conversation | None:
        row = self._mine(user_id, conversation_id)
        return row.conversation if row else None

    async def messages(
        self, user_id: UUID, conversation_id: UUID, last: int | None = None
    ) -> list[Message]:
        row = self._mine(user_id, conversation_id)
        if row is None:
            return []
        return list(row.messages[-last:] if last else row.messages)

    async def add_message(
        self, user_id: UUID, conversation_id: UUID, message: Message, at: datetime
    ) -> None:
        row = self._mine(user_id, conversation_id)
        if row is None:
            return
        row.messages.append(message)
        questions = row.conversation.questions + (message.role is MessageRole.USER)
        row.conversation = replace(row.conversation, updated_at=at, questions=questions)

    async def set_message(
        self, user_id: UUID, message_id: UUID, status: MessageStatus, at: datetime
    ) -> None:
        for row in self._rows.values():
            if row.user_id != user_id:
                continue
            for i, message in enumerate(row.messages):
                if message.id == message_id:
                    row.messages[i] = replace(message, status=status)
                    row.conversation = replace(row.conversation, updated_at=at)

    async def find(self, user_id: UUID, level: Level, query_key: str | None) -> list[Conversation]:
        rows = self._list(user_id, level)
        if query_key:
            rows = [
                r
                for r in rows
                if query_key in search_key(r.conversation.title)
                or any(query_key in search_key(m.text) for m in r.messages)
            ]
        rows.sort(key=lambda r: r.conversation.updated_at, reverse=True)
        rows.sort(key=lambda r: not r.conversation.pinned)
        return [r.conversation for r in rows]

    async def count(self, user_id: UUID, level: Level) -> int:
        return len(self._list(user_id, level))

    async def oldest_unpinned(self, user_id: UUID, level: Level) -> UUID | None:
        rows = [r for r in self._list(user_id, level) if not r.conversation.pinned]
        if not rows:
            return None
        return min(rows, key=lambda r: r.conversation.updated_at).conversation.id

    async def pinned_count(self, user_id: UUID, level: Level) -> int:
        return sum(r.conversation.pinned for r in self._list(user_id, level))

    async def update(self, user_id: UUID, conversation: Conversation) -> None:
        row = self._mine(user_id, conversation.id)
        if row is not None:
            row.conversation = replace(
                row.conversation,
                title=conversation.title,
                title_source=conversation.title_source,
                pinned=conversation.pinned,
            )

    async def save_share(
        self, user_id: UUID, conversation_id: UUID, token: str, copy: SharedCopy
    ) -> None:
        row = self._mine(user_id, conversation_id)
        if row is not None:
            row.shared = copy
            row.conversation = replace(
                row.conversation, share_token=token, shared_at=copy.shared_at
            )

    async def drop_share(self, user_id: UUID, conversation_id: UUID) -> None:
        row = self._mine(user_id, conversation_id)
        if row is not None:
            row.shared = None
            row.conversation = replace(row.conversation, share_token=None, shared_at=None)

    async def shared(self, token: str) -> SharedCopy | None:
        for row in self._rows.values():
            if row.conversation.share_token == token:
                return row.shared
        return None

    async def delete(self, user_id: UUID, conversation_id: UUID) -> bool:
        if self._mine(user_id, conversation_id) is None:
            return False
        del self._rows[conversation_id]
        return True

    async def delete_all(self, user_id: UUID, level: Level) -> int:
        doomed = [r.conversation.id for r in self._list(user_id, level)]
        for conversation_id in doomed:
            del self._rows[conversation_id]
        return len(doomed)

    async def forget(self, user_id: UUID) -> None:
        for conversation_id in [k for k, r in self._rows.items() if r.user_id == user_id]:
            del self._rows[conversation_id]
