"""The assistant endpoint (B16): questions answered only from our sources, with citations."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from pharmavique.assistant.application.ask import MAX_QUESTION, AskAssistant
from pharmavique.assistant.application.history import ConversationService, PendingQuestion
from pharmavique.assistant.application.ports import AssistantBusy
from pharmavique.assistant.domain.answers import Answer, Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.assistant.domain.history import (
    ConversationFull,
    ConversationNotFound,
    level_for_roles,
)
from pharmavique.bootstrap.api_auth import signed_in_for_ai
from pharmavique.bootstrap.api_drugs import DISCLAIMER
from pharmavique.bootstrap.api_history import HistoryCheckOut, history_for_request
from pharmavique.bootstrap.features import Features, get_features
from pharmavique.bootstrap.trust import GRADE_LABEL_AR, TrustGrade, grade_of_citation
from pharmavique.shared_kernel.principal import Principal

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])
_log = logging.getLogger(__name__)

# A phone browser drops a request that stays silent for about a minute ("Load failed"), and a
# language model on a free plan can take that long. An answer that is not ready after
# HEARTBEAT_AFTER seconds is sent as a stream that starts with blank bytes, one every
# HEARTBEAT_EVERY seconds, and ends with the JSON. A failure after the stream began cannot change
# the HTTP status, so it is sent as {"error": {"status": ..., "detail": ...}}.
HEARTBEAT_AFTER = 8.0
HEARTBEAT_EVERY = 8.0


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    level: Level = Level.PATIENT
    register_number: str | None = Field(default=None, max_length=40)
    spoken: bool = False  # the answer will be read aloud: written in Saudi dialect
    # Earlier turns, oldest first, for a caller whose conversation is not saved (a guest). A saved
    # conversation's earlier turns are read on the server and this is ignored.
    history: list[TurnIn] = Field(default_factory=list, max_length=20)
    # The saved conversation to continue; none starts a new one (signed in, ADR-022).
    conversation_id: UUID | None = None
    # Compare the drug with the medicines I take now (signed in). The comparison runs on the server
    # from recorded interactions; the language model never sees my medicines.
    use_history: bool = False


class CitationOut(BaseModel):
    number: int  # the [n] the answer uses
    source_id: str
    title: str
    url: str | None
    kind: str
    published: str | None
    trust_grade: TrustGrade
    trust_label_ar: str


class AnswerOut(BaseModel):
    answer: str
    citations: list[CitationOut]
    grounded: bool  # registry records are cited
    web: bool  # pages from the open web are cited: unverified, shown with that label (ADR-017)
    general: bool  # general information, not from the SFDA registry: shown with that label
    urgent: bool  # the question looked like an emergency: the reply says to call 997
    refused: bool
    level: Level
    tools_used: list[str]
    history_check: HistoryCheckOut | None = None  # only when asked for, signed in
    # The saved conversation this answer belongs to; none when nothing is saved (a guest).
    conversation_id: UUID | None = None
    new_conversation: bool = False  # the app then asks for the model's title
    disclaimer: str = DISCLAIMER


def get_assistant(request: Request) -> AskAssistant:
    assistant: AskAssistant | None = request.app.state.assistant
    if assistant is None:
        raise HTTPException(
            status_code=503,
            detail="the assistant is not configured: set PHARMAVIQUE_GROQ_API_KEY "
            "(or PHARMAVIQUE_OPENROUTER_API_KEY with PHARMAVIQUE_LLM_PROVIDER=openrouter)",
        )
    return assistant


def _conversations(
    request: Request, principal: Principal | None, features: Features
) -> ConversationService | None:
    service: ConversationService | None = request.app.state.conversations
    if principal is None or not features.chat_history:
        return None
    return service


async def _begin(
    service: ConversationService | None, principal: Principal | None, body: AskIn, level: Level
) -> PendingQuestion | None:
    """Save the question before the model answers. Storage trouble never stops the answer: the
    question is then answered without being saved (for example before the migration ran)."""
    if service is None or principal is None:
        return None
    try:
        return await service.begin(principal.user_id, body.conversation_id, level, body.question)
    except ConversationNotFound as error:
        raise HTTPException(status_code=404, detail="conversation not found") from error
    except ConversationFull as error:
        raise HTTPException(
            status_code=409, detail="this conversation is full: start a new one"
        ) from error
    except Exception as error:
        _log.error("saving a question failed", extra={"error": type(error).__name__})
        return None


async def _settle(
    service: ConversationService | None,
    principal: Principal | None,
    pending: PendingQuestion | None,
    out: AnswerOut | None,
) -> None:
    """Save the answer, or mark the question failed when `out` is None."""
    if service is None or principal is None or pending is None:
        return
    try:
        if out is None:
            await service.failed(principal.user_id, pending)
        else:
            payload = out.model_dump(mode="json", exclude={"disclaimer", "conversation_id"})
            await service.answered(principal.user_id, pending, out.answer, payload)
    except Exception as error:
        _log.error("saving an answer failed", extra={"error": type(error).__name__})


@router.post("/ask", response_model=AnswerOut, summary="Ask about a drug; cited answers only")
async def ask(
    body: AskIn,
    request: Request,
    principal: Annotated[Principal | None, Depends(signed_in_for_ai)],
    assistant: Annotated[AskAssistant, Depends(get_assistant)],
    features: Annotated[Features, Depends(get_features)],
) -> AnswerOut | StreamingResponse:
    # A signed-in account always gets its role's level, so a saved list has one level (ADR-022).
    level = level_for_roles(principal.roles, body.level) if principal else body.level
    service = _conversations(request, principal, features)
    pending = await _begin(service, principal, body, level)
    conversation_id = pending.conversation.id if pending else None
    saved_turns = pending.history if pending else None

    async def answer() -> AnswerOut:
        history = (
            await history_for_request(request, principal, body.register_number)
            if body.use_history
            else None
        )
        turns = (
            list(saved_turns)
            if saved_turns is not None
            else [Turn(t.role, t.text) for t in body.history]
        )
        try:
            result = await assistant.ask(
                body.question, level, body.register_number, spoken=body.spoken, history=turns
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except AssistantBusy as error:
            raise HTTPException(
                status_code=429,
                detail="the assistant is busy for a moment, try again in a few seconds",
                headers={"Retry-After": "10"},
            ) from error
        out = answer_out(result)
        out.history_check = history
        out.conversation_id = conversation_id
        out.new_conversation = bool(pending and pending.created)
        return out

    async def answer_and_save() -> AnswerOut:
        try:
            out = await answer()
        except BaseException:
            await _settle(service, principal, pending, None)
            raise
        await _settle(service, principal, pending, out)
        return out

    task = asyncio.ensure_future(answer_and_save())
    done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_AFTER)
    if done:
        try:
            return task.result()  # an HTTPException keeps its own status
        except HTTPException as error:
            if conversation_id is not None:  # the app can show the question with "try again"
                error.headers = {**(error.headers or {}), "X-Conversation-Id": str(conversation_id)}
            raise

    async def stream() -> AsyncIterator[bytes]:
        try:
            while True:
                finished, _ = await asyncio.wait({task}, timeout=HEARTBEAT_EVERY)
                if finished:
                    break
                yield b" "
            try:
                yield task.result().model_dump_json().encode()
            except HTTPException as error:
                failure = {"status": error.status_code, "detail": error.detail}
                yield json.dumps({"error": _with_conversation(failure, conversation_id)}).encode()
            except Exception:  # the answer is lost; say so instead of closing the connection
                failure = {"status": 500, "detail": "assistant failed"}
                yield json.dumps({"error": _with_conversation(failure, conversation_id)}).encode()
        finally:
            task.cancel()  # the person left: stop paying for the answer

    return StreamingResponse(
        stream(), media_type="application/json", headers={"Cache-Control": "no-store"}
    )


def _with_conversation(
    failure: dict[str, object], conversation_id: UUID | None
) -> dict[str, object]:
    if conversation_id is not None:
        failure["conversation_id"] = str(conversation_id)
    return failure


def answer_out(answer: Answer) -> AnswerOut:
    # The runner numbers citations 1..n in the order the answer's [n] refer to them.
    numbered = list(enumerate(answer.citations, start=1))
    return AnswerOut(
        answer=answer.text,
        citations=[
            CitationOut(
                number=n,
                source_id=c.source_id,
                title=c.title,
                url=c.url,
                kind=c.kind,
                published=c.published,
                trust_grade=grade_of_citation(c.kind, c.source_id, c.url),
                trust_label_ar=GRADE_LABEL_AR[grade_of_citation(c.kind, c.source_id, c.url)],
            )
            for n, c in numbered
        ],
        grounded=answer.grounded,
        web=any(c.kind == "web" for c in answer.citations),
        general=answer.general,
        urgent=answer.urgent,
        refused=answer.refused,
        level=answer.level,
        tools_used=list(answer.tools_used),
    )
