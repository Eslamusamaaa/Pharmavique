"""The assistant endpoint (B16): questions answered only from our sources, with citations."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from pharmavique.assistant.application.ask import MAX_QUESTION, AskAssistant
from pharmavique.assistant.application.ports import AssistantBusy
from pharmavique.assistant.domain.answers import Answer, Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.bootstrap.api_auth import optional_principal
from pharmavique.bootstrap.api_drugs import DISCLAIMER
from pharmavique.bootstrap.api_history import HistoryCheckOut, history_for_request
from pharmavique.shared_kernel.principal import Principal

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    level: Level = Level.PATIENT
    register_number: str | None = Field(default=None, max_length=40)
    spoken: bool = False  # the answer will be read aloud: written in Saudi dialect
    # Earlier turns of this conversation, oldest first; the server keeps no conversation.
    history: list[TurnIn] = Field(default_factory=list, max_length=20)
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


@router.post("/ask", response_model=AnswerOut, summary="Ask about a drug; cited answers only")
async def ask(
    body: AskIn,
    request: Request,
    assistant: Annotated[AskAssistant, Depends(get_assistant)],
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> AnswerOut:
    history = (
        await history_for_request(request, principal, body.register_number)
        if body.use_history
        else None
    )
    try:
        answer = await assistant.ask(
            body.question,
            body.level,
            body.register_number,
            spoken=body.spoken,
            history=[Turn(t.role, t.text) for t in body.history],
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AssistantBusy as error:
        raise HTTPException(
            status_code=429,
            detail="the assistant is busy for a moment, try again in a few seconds",
            headers={"Retry-After": "10"},
        ) from error
    out = answer_out(answer)
    out.history_check = history
    return out


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
