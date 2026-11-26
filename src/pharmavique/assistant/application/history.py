"""Use cases of saved conversations: save a question and its answer, list, search, rename, pin,
delete, share. Every per-person call names the person; storage limits each query to that person.

A question is saved before the model answers (status `pending`), so a failure leaves it in the
conversation marked `failed` and the app can offer "try again". Asking the same question again in
that conversation replaces the failed one instead of adding a second copy.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.assistant.domain.history import (
    MAX_CONVERSATIONS,
    MAX_PINNED,
    MAX_QUESTIONS,
    Conversation,
    ConversationFull,
    ConversationNotFound,
    Message,
    MessageRole,
    MessageStatus,
    SharedCopy,
    TitleSource,
    TooManyPinned,
    clean_title,
    search_key,
    title_from_question,
)
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.ports import Clock

HISTORY_MESSAGES = 12  # read for the model; `prepare_history` keeps the last six turns


class ConversationStore(Protocol):
    async def create(self, user_id: UUID, conversation: Conversation) -> None: ...

    async def get(self, user_id: UUID, conversation_id: UUID) -> Conversation | None: ...

    async def messages(
        self, user_id: UUID, conversation_id: UUID, last: int | None = None
    ) -> list[Message]:
        """Oldest first; `last` keeps only the most recent ones."""
        ...

    async def add_message(
        self, user_id: UUID, conversation_id: UUID, message: Message, at: datetime
    ) -> None:
        """Adds the message and moves the conversation to the top of its list."""
        ...

    async def set_message(
        self, user_id: UUID, message_id: UUID, status: MessageStatus, at: datetime
    ) -> None: ...

    async def find(self, user_id: UUID, level: Level, query_key: str | None) -> list[Conversation]:
        """Pinned first, then the most recently used. `query_key` (normalized) matches the title,
        a question or an answer."""
        ...

    async def count(self, user_id: UUID, level: Level) -> int: ...

    async def oldest_unpinned(self, user_id: UUID, level: Level) -> UUID | None: ...

    async def pinned_count(self, user_id: UUID, level: Level) -> int: ...

    async def update(self, user_id: UUID, conversation: Conversation) -> None:
        """Title, title source, pinned and share fields."""
        ...

    async def save_share(
        self, user_id: UUID, conversation_id: UUID, token: str, copy: SharedCopy
    ) -> None: ...

    async def drop_share(self, user_id: UUID, conversation_id: UUID) -> None: ...

    async def shared(self, token: str) -> SharedCopy | None:
        """The copy behind a share link; anyone with the link may read it."""
        ...

    async def delete(self, user_id: UUID, conversation_id: UUID) -> bool: ...

    async def delete_all(self, user_id: UUID, level: Level) -> int: ...

    async def forget(self, user_id: UUID) -> None:
        """Delete every conversation of the person (the account is being deleted)."""
        ...


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    """A question saved before the model answers, with what the model may see of the past."""

    conversation: Conversation
    question_id: UUID
    history: tuple[Turn, ...]
    created: bool  # a new conversation was started for it


class ConversationService:
    def __init__(self, store: ConversationStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    # ---- asking -----------------------------------------------------------------------------
    async def begin(
        self, user_id: UUID, conversation_id: UUID | None, level: Level, question: str
    ) -> PendingQuestion:
        now = self._clock.now()
        if conversation_id is None:
            conversation = await self._start(user_id, level, question, now)
            question_id = await self._add_question(user_id, conversation.id, question, now)
            return PendingQuestion(conversation, question_id, (), created=True)
        conversation = await self._own(user_id, conversation_id)
        earlier = await self._store.messages(user_id, conversation.id, last=HISTORY_MESSAGES)
        last = earlier[-1] if earlier else None
        if (
            last is not None
            and last.role is MessageRole.USER
            and last.status is not MessageStatus.OK
            and " ".join(last.text.split()) == " ".join(question.split())
        ):
            await self._store.set_message(user_id, last.id, MessageStatus.PENDING, now)
            question_id, earlier = last.id, earlier[:-1]
        else:
            if conversation.questions >= MAX_QUESTIONS:
                raise ConversationFull
            question_id = await self._add_question(user_id, conversation.id, question, now)
        history = tuple(Turn(m.role.value, m.text) for m in earlier if m.status is MessageStatus.OK)
        return PendingQuestion(conversation, question_id, history, created=False)

    async def answered(
        self,
        user_id: UUID,
        pending: PendingQuestion,
        answer: str,
        payload: dict[str, Any],
    ) -> None:
        now = self._clock.now()
        await self._store.set_message(user_id, pending.question_id, MessageStatus.OK, now)
        message = Message(uuid4(), MessageRole.ASSISTANT, answer, MessageStatus.OK, now, payload)
        await self._store.add_message(user_id, pending.conversation.id, message, now)

    async def failed(self, user_id: UUID, pending: PendingQuestion) -> None:
        now = self._clock.now()
        await self._store.set_message(user_id, pending.question_id, MessageStatus.FAILED, now)

    # ---- reading ----------------------------------------------------------------------------
    async def conversations(
        self, user_id: UUID, level: Level, query: str | None = None
    ) -> tuple[list[Conversation], int]:
        """The list (searched when `query` is given) and how many the list holds in all."""
        key = search_key(query) if query and query.strip() else None
        found = await self._store.find(user_id, level, key or None)
        return found, await self._store.count(user_id, level)

    async def open(
        self, user_id: UUID, conversation_id: UUID
    ) -> tuple[Conversation, list[Message]]:
        conversation = await self._own(user_id, conversation_id)
        return conversation, await self._store.messages(user_id, conversation.id)

    # ---- changing ---------------------------------------------------------------------------
    async def rename(self, user_id: UUID, conversation_id: UUID, title: str) -> Conversation:
        conversation = await self._own(user_id, conversation_id)
        changed = replace(conversation, title=clean_title(title), title_source=TitleSource.PERSON)
        await self._store.update(user_id, changed)
        return changed

    async def model_title(
        self, user_id: UUID, conversation_id: UUID, title: str | None
    ) -> Conversation:
        """Store the model's title, unless a title was already written (by the model or the
        person). `None` (the model failed) keeps the title cut from the first question."""
        conversation = await self._own(user_id, conversation_id)
        if title is None or conversation.title_source is not TitleSource.QUESTION:
            return conversation
        try:
            cleaned = clean_title(title)
        except InvariantViolation:
            return conversation
        changed = replace(conversation, title=cleaned, title_source=TitleSource.MODEL)
        await self._store.update(user_id, changed)
        return changed

    async def first_question(self, user_id: UUID, conversation_id: UUID) -> tuple[str, str] | None:
        """The first question and its answer, for the model that writes the title."""
        messages = await self._store.messages(user_id, conversation_id)
        question = next((m for m in messages if m.role is MessageRole.USER), None)
        answer = next((m for m in messages if m.role is MessageRole.ASSISTANT), None)
        if question is None or answer is None:
            return None
        return question.text, answer.text

    async def pin(self, user_id: UUID, conversation_id: UUID, pinned: bool) -> Conversation:
        conversation = await self._own(user_id, conversation_id)
        adding = pinned and not conversation.pinned
        if adding and await self._store.pinned_count(user_id, conversation.level) >= MAX_PINNED:
            raise TooManyPinned
        changed = replace(conversation, pinned=pinned)
        await self._store.update(user_id, changed)
        return changed

    async def delete(self, user_id: UUID, conversation_id: UUID) -> None:
        if not await self._store.delete(user_id, conversation_id):
            raise ConversationNotFound

    async def delete_all(self, user_id: UUID, level: Level) -> int:
        return await self._store.delete_all(user_id, level)

    async def forget(self, user_id: UUID) -> None:
        await self._store.forget(user_id)

    # ---- sharing ----------------------------------------------------------------------------
    async def share(self, user_id: UUID, conversation_id: UUID) -> str:
        """Share the conversation as it is now; sharing again updates the same link."""
        conversation, messages = await self.open(user_id, conversation_id)
        token = conversation.share_token or secrets.token_urlsafe(16)
        now = self._clock.now()
        copy = SharedCopy(conversation.title, conversation.level, now, _shown(messages))
        await self._store.save_share(user_id, conversation.id, token, copy)
        return token

    async def unshare(self, user_id: UUID, conversation_id: UUID) -> None:
        conversation = await self._own(user_id, conversation_id)
        await self._store.drop_share(user_id, conversation.id)

    async def shared(self, token: str) -> SharedCopy:
        copy = await self._store.shared(token) if token else None
        if copy is None:
            raise ConversationNotFound
        return copy

    # ---- helpers ----------------------------------------------------------------------------
    async def _own(self, user_id: UUID, conversation_id: UUID) -> Conversation:
        conversation = await self._store.get(user_id, conversation_id)
        if conversation is None:
            raise ConversationNotFound
        return conversation

    async def _start(
        self, user_id: UUID, level: Level, question: str, now: datetime
    ) -> Conversation:
        while await self._store.count(user_id, level) >= MAX_CONVERSATIONS:
            oldest = await self._store.oldest_unpinned(user_id, level)
            if oldest is None:  # cannot happen while MAX_PINNED < MAX_CONVERSATIONS
                break
            await self._store.delete(user_id, oldest)
        conversation = Conversation(
            id=uuid4(),
            level=level,
            title=title_from_question(question),
            title_source=TitleSource.QUESTION,
            pinned=False,
            created_at=now,
            updated_at=now,
            questions=0,
        )
        await self._store.create(user_id, conversation)
        return conversation

    async def _add_question(
        self, user_id: UUID, conversation_id: UUID, question: str, now: datetime
    ) -> UUID:
        message = Message(uuid4(), MessageRole.USER, question, MessageStatus.PENDING, now)
        await self._store.add_message(user_id, conversation_id, message, now)
        return message.id


def _shown(messages: Sequence[Message]) -> tuple[Message, ...]:
    """A shared copy shows answered questions and their answers, not a question still waiting."""
    return tuple(m for m in messages if m.status is MessageStatus.OK)
