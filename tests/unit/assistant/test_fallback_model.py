"""A chat model with a backup: used when the first one is rate limited or too slow."""

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx2
import openai
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from pharmavique.assistant.infrastructure.fallback_model import FallbackChatModel


class Model:
    def __init__(self, name: str, reply: AIMessage | Exception, delay: float = 0.0) -> None:
        self.model_name = name
        self.reply = reply
        self.delay = delay
        self.bound_with: list[str] = []
        self.calls = 0

    def bind_tools(self, tools: Sequence[Any]) -> "Model":
        self.bound_with = [str(t) for t in tools]
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def rate_limit() -> openai.RateLimitError:
    request = httpx2.Request("POST", "https://x.test")
    return openai.RateLimitError("limit", response=httpx2.Response(429, request=request), body=None)


async def ask(model: FallbackChatModel) -> AIMessage:
    return await model.bind_tools(["t"]).ainvoke([HumanMessage("q")])


async def test_the_first_model_answers_when_it_can() -> None:
    first, backup = Model("a", AIMessage("from a")), Model("b", AIMessage("from b"))

    answer = await ask(FallbackChatModel(first, backup))

    assert answer.content == "from a"
    assert backup.calls == 0


async def test_a_rate_limit_moves_to_the_backup_with_the_same_tools() -> None:
    first, backup = Model("a", rate_limit()), Model("b", AIMessage("from b"))

    answer = await ask(FallbackChatModel(first, backup))

    assert answer.content == "from b"
    assert backup.bound_with == ["t"]


async def test_a_model_that_is_too_slow_moves_to_the_backup() -> None:
    first, backup = Model("a", AIMessage("late"), delay=1), Model("b", AIMessage("from b"))

    answer = await ask(FallbackChatModel(first, backup, first_timeout=0.05))

    assert answer.content == "from b"


async def test_a_dropped_connection_moves_to_the_backup() -> None:
    request = httpx2.Request("POST", "https://x.test")
    first = Model("a", openai.APIConnectionError(request=request))
    backup = Model("b", AIMessage("from b"))

    answer = await ask(FallbackChatModel(first, backup))

    assert answer.content == "from b"


async def test_when_both_fail_the_backups_error_is_raised() -> None:
    first, backup = Model("a", rate_limit()), Model("b", rate_limit())

    with pytest.raises(openai.RateLimitError):
        await ask(FallbackChatModel(first, backup))


def test_the_model_name_is_the_first_models() -> None:
    assert (
        FallbackChatModel(Model("a", AIMessage("x")), Model("b", AIMessage("y"))).model_name == "a"
    )


def status_error(code: int) -> openai.APIStatusError:
    request = httpx2.Request("POST", "https://x.test")
    return openai.APIStatusError(
        "Request too large for model on tokens per minute (TPM): Limit 8000, Requested 8401",
        response=httpx2.Response(code, request=request),
        body=None,
    )


@pytest.mark.parametrize("code", [413, 500, 502, 503])
async def test_a_request_too_large_or_a_provider_error_moves_to_the_backup(code: int) -> None:
    # Real case (2026-11-23): Groq's free plan refused a long question with 413, and the
    # person got a 500 instead of the backup's answer.
    first, backup = Model("a", status_error(code)), Model("b", AIMessage("from b"))

    answer = await ask(FallbackChatModel(first, backup))

    assert answer.content == "from b"


async def test_a_bad_request_is_not_sent_to_the_backup() -> None:
    first, backup = Model("a", status_error(400)), Model("b", AIMessage("from b"))

    with pytest.raises(openai.APIStatusError):
        await ask(FallbackChatModel(first, backup))
    assert backup.calls == 0
