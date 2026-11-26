"""Saved assistant conversations (ADR-022): list and search, read, rename, pin, delete, the model's
title, share links, and the public read of a shared copy.

Every route except the shared copy needs a signed-in account, and each one sees only its own
conversations (also enforced by row-level security). A list is the account's: one level, from the
account role; only an operator picks the level. Behind the `chat_history` flag.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from pharmavique.assistant.application.history import ConversationService, TitleWriter
from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.history import (
    MAX_CONVERSATIONS,
    MAX_PINNED,
    MAX_TITLE,
    WARN_AT,
    Conversation,
    ConversationNotFound,
    Message,
    TooManyPinned,
    level_for_roles,
)
from pharmavique.bootstrap.api_auth import current_principal
from pharmavique.bootstrap.api_drugs import DISCLAIMER
from pharmavique.bootstrap.features import require_feature
from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.principal import Principal

router = APIRouter(
    prefix="/v1/assistant/conversations",
    tags=["assistant"],
    dependencies=[Depends(require_feature("chat_history"))],
)
shared_router = APIRouter(
    prefix="/v1/shared", tags=["assistant"], dependencies=[Depends(require_feature("chat_history"))]
)

Me = Annotated[Principal, Depends(current_principal)]


class ConversationOut(BaseModel):
    id: UUID
    title: str
    level: Level
    pinned: bool
    questions: int
    created_at: datetime
    updated_at: datetime
    shared: bool
    share_token: str | None


class ConversationListOut(BaseModel):
    level: Level
    conversations: list[ConversationOut]
    total: int  # in the whole list, not only what a search found
    limit: int = MAX_CONVERSATIONS  # at the limit the oldest unpinned one makes room
    warn_at: int = WARN_AT
    max_pinned: int = MAX_PINNED


class MessageOut(BaseModel):
    id: UUID
    role: str
    text: str
    status: str  # ok, pending (being answered) or failed (offer "try again")
    created_at: datetime
    # An answer as the app showed it: citations with trust grades, flags, the medicines card.
    answer: dict[str, Any] | None


class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    disclaimer: str = DISCLAIMER


class ConversationChange(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE * 2)
    pinned: bool | None = None


class ShareOut(BaseModel):
    token: str
    path: str  # the app's page for the link: /shared/<token>


class SharedOut(BaseModel):
    title: str
    level: Level
    shared_at: datetime
    messages: list[MessageOut]
    disclaimer: str = DISCLAIMER


class DeletedOut(BaseModel):
    deleted: int


def get_conversations(request: Request) -> ConversationService:
    service: ConversationService | None = request.app.state.conversations
    if service is None:
        raise HTTPException(status_code=503, detail="conversations need the database")
    return service


Service = Annotated[ConversationService, Depends(get_conversations)]


def _out(conversation: Conversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        level=conversation.level,
        pinned=conversation.pinned,
        questions=conversation.questions,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        shared=conversation.share_token is not None,
        share_token=conversation.share_token,
    )


def _message(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role.value,
        text=message.text,
        status=message.status.value,
        created_at=message.created_at,
        answer=message.payload or None,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="conversation not found")


@router.get("", response_model=ConversationListOut, summary="My saved conversations")
async def list_conversations(
    me: Me,
    service: Service,
    q: Annotated[str | None, Query(max_length=100)] = None,
    level: Level = Level.PATIENT,
) -> ConversationListOut:
    """Pinned first, then the most recently used. `q` searches titles, questions and answers.
    `level` is only read for an operator; everyone else gets their account's list."""
    mine = level_for_roles(me.roles, level)
    found, total = await service.conversations(me.user_id, mine, q)
    return ConversationListOut(level=mine, conversations=[_out(c) for c in found], total=total)


@router.delete("", response_model=DeletedOut, summary="Delete every conversation in my list")
async def delete_all(me: Me, service: Service, level: Level = Level.PATIENT) -> DeletedOut:
    deleted = await service.delete_all(me.user_id, level_for_roles(me.roles, level))
    return DeletedOut(deleted=deleted)


@router.get("/{conversation_id}", response_model=ConversationDetailOut, summary="One conversation")
async def read_conversation(
    conversation_id: UUID, me: Me, service: Service
) -> ConversationDetailOut:
    try:
        conversation, messages = await service.open(me.user_id, conversation_id)
    except ConversationNotFound as error:
        raise _not_found() from error
    return ConversationDetailOut(
        conversation=_out(conversation), messages=[_message(m) for m in messages]
    )


@router.patch("/{conversation_id}", response_model=ConversationOut, summary="Rename or pin")
async def change_conversation(
    conversation_id: UUID, change: ConversationChange, me: Me, service: Service
) -> ConversationOut:
    try:
        conversation = None
        if change.title is not None:
            conversation = await service.rename(me.user_id, conversation_id, change.title)
        if change.pinned is not None:
            conversation = await service.pin(me.user_id, conversation_id, change.pinned)
        if conversation is None:
            conversation, _ = await service.open(me.user_id, conversation_id)
    except ConversationNotFound as error:
        raise _not_found() from error
    except TooManyPinned as error:
        raise HTTPException(
            status_code=409, detail=f"at most {MAX_PINNED} pinned conversations"
        ) from error
    except InvariantViolation as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _out(conversation)


@router.delete("/{conversation_id}", status_code=204, summary="Delete one conversation")
async def delete_conversation(conversation_id: UUID, me: Me, service: Service) -> Response:
    try:
        await service.delete(me.user_id, conversation_id)
    except ConversationNotFound as error:
        raise _not_found() from error
    return Response(status_code=204)


@router.post(
    "/{conversation_id}/title",
    response_model=ConversationOut,
    summary="Let the model name the conversation after its first answer",
)
async def write_title(
    conversation_id: UUID, request: Request, me: Me, service: Service
) -> ConversationOut:
    writer: TitleWriter | None = request.app.state.title_writer
    try:
        conversation = await service.write_title(me.user_id, conversation_id, writer)
    except ConversationNotFound as error:
        raise _not_found() from error
    return _out(conversation)


@router.post("/{conversation_id}/share", response_model=ShareOut, summary="Share by link")
async def share(conversation_id: UUID, me: Me, service: Service) -> ShareOut:
    """Anyone with the link sees the conversation as it is now; sharing again updates the same
    link. Deleting the conversation ends the link (owner's decisions, 2026-11-26)."""
    try:
        token = await service.share(me.user_id, conversation_id)
    except ConversationNotFound as error:
        raise _not_found() from error
    return ShareOut(token=token, path=f"/shared/{token}")


@router.delete("/{conversation_id}/share", status_code=204, summary="Stop sharing")
async def unshare(conversation_id: UUID, me: Me, service: Service) -> Response:
    try:
        await service.unshare(me.user_id, conversation_id)
    except ConversationNotFound as error:
        raise _not_found() from error
    return Response(status_code=204)


@shared_router.get("/{token}", response_model=SharedOut, summary="A shared conversation")
async def read_shared(token: str, response: Response, service: Service) -> SharedOut:
    """Public: anyone with the link. Not for search engines."""
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    if len(token) > 64:
        raise HTTPException(status_code=404, detail="this shared conversation no longer exists")
    try:
        copy = await service.shared(token)
    except ConversationNotFound as error:
        raise HTTPException(
            status_code=404,
            detail="this shared conversation no longer exists",
            headers={"X-Robots-Tag": "noindex, nofollow"},
        ) from error
    return SharedOut(
        title=copy.title,
        level=copy.level,
        shared_at=copy.shared_at,
        messages=[_message(m) for m in copy.messages],
    )
