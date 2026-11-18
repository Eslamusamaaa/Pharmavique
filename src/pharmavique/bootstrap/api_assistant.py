"""The assistant endpoint (B16): questions answered only from our sources, with citations."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from pharmavique.assistant.application.ask import MAX_QUESTION, AskAssistant
from pharmavique.assistant.domain.answers import Level
from pharmavique.bootstrap.api_drugs import DISCLAIMER

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    level: Level = Level.PATIENT
    register_number: str | None = Field(default=None, max_length=40)


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
    grounded: bool
    refused: bool
    level: Level
    tools_used: list[str]
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
async def ask(body: AskIn, assistant: Annotated[AskAssistant, Depends(get_assistant)]) -> AnswerOut:
    try:
        answer = await assistant.ask(body.question, body.level, body.register_number)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
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
        refused=answer.refused,
        level=answer.level,
        tools_used=list(answer.tools_used),
    )
