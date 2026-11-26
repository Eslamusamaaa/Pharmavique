"""Saved conversations with the assistant (docs/PHASE_1_DECISIONS.md, ADR-022).

A person has one list of conversations per assistant level; the level comes from the account role
(an operator picks it). A conversation keeps every question and answer as they were shown, so
reopening it shows the same citations and trust grades, with the date of each answer. The model is
still given only the last few turns (`conversation.prepare_history`).

Limits: 50 conversations per list (the oldest unpinned one is deleted to make room), 10 pinned
(never deleted to make room), 100 questions per conversation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pharmavique.assistant.domain.answers import Level
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.text import normalize_text

MAX_CONVERSATIONS = 50
WARN_AT = 45  # the app says the list is nearly full
MAX_PINNED = 10
MAX_QUESTIONS = 100
MAX_TITLE = 80
QUESTION_TITLE = 40  # a title cut from the first question


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    OK = "ok"
    PENDING = "pending"  # a question whose answer is being written
    FAILED = "failed"  # no answer came: the app offers "try again"


class TitleSource(StrEnum):
    QUESTION = "question"  # cut from the first question until the model writes one
    MODEL = "model"
    PERSON = "person"  # renamed by the person: never replaced


class ConversationNotFound(Exception):
    """No such conversation for this person, or no such share link."""


class ConversationFull(Exception):
    """The conversation already has the most questions it may hold."""


class TooManyPinned(Exception):
    """The list already has the most pinned conversations it may hold."""


@dataclass(frozen=True, slots=True)
class Message:
    id: UUID
    role: MessageRole
    text: str
    status: MessageStatus
    created_at: datetime
    # For an answer: everything the app showed (citations, trust grades, flags, the medicines card).
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    level: Level
    title: str
    title_source: TitleSource
    pinned: bool
    created_at: datetime
    updated_at: datetime
    questions: int
    share_token: str | None = None
    shared_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SharedCopy:
    """What a share link shows: the conversation as it was when it was shared."""

    title: str
    level: Level
    shared_at: datetime
    messages: tuple[Message, ...]


def title_from_question(question: str) -> str:
    text = " ".join(question.split())
    if len(text) <= QUESTION_TITLE:
        return text
    return text[:QUESTION_TITLE].rstrip() + "…"


def clean_title(title: str) -> str:
    """A title the person typed or the model wrote: one line, no quotes around it, not too long."""
    text = " ".join(title.split()).strip("\"'“”«»`*# ")
    if not text:
        raise InvariantViolation("a title cannot be empty")
    if len(text) > MAX_TITLE:
        text = text[:MAX_TITLE].rstrip() + "…"
    return text


def search_key(text: str) -> str:
    """The text as search compares it: the drug search's Arabic and Latin normalization."""
    return normalize_text(text)


def level_for_roles(roles: frozenset[str], asked: Level) -> Level:
    """The assistant level of an account: from its role, so every conversation in a list has the
    same level. Only an operator chooses (`asked`)."""
    if "operator" in roles:
        return asked
    if "company" in roles:
        return Level.CLINICAL
    if "pharmacist" in roles:
        return Level.PHARMACIST
    return Level.PATIENT
