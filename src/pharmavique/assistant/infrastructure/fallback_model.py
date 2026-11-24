"""A chat model with backups, for the free plans' limits.

The first model is Groq's `gpt-oss-120b`, whose free plan allows 8,000 tokens a minute: one answer
takes most of that, so a second question in the same minute is refused, and a long conversation is
refused outright (HTTP 413). The backups are free models elsewhere (Gemma 4 on Cloudflare Workers
AI, then free models on OpenRouter), tried in order. Any failure of one model, whatever it is,
moves the same call to the next: a person gets an answer while any of them can give one. Only when
every model fails is the last error raised (the assistant turns it into a busy answer).

A model that answered "rate limited" is skipped for a minute, so the next questions do not wait
for a refusal first. All are LangChain chat models with `bind_tools`.
"""

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Any

import openai
from langchain_core.messages import AIMessage, BaseMessage

FIRST_TIMEOUT = 25.0  # seconds before the first model's backup is tried
BACKUP_TIMEOUT = 45.0  # for the backups that are not the last one (Gemma took 31 to 42 s)
RATE_LIMIT_PAUSE = 60.0  # seconds a rate-limited model is skipped (the limits are per minute)


class _Chain:
    """What the bound and unbound models share: which model is resting until when."""

    def __init__(self, count: int, clock: Callable[[], float]) -> None:
        self.resting_until = [0.0] * count
        self.clock = clock


class _BoundWithBackup:
    def __init__(self, models: Sequence[Any], timeouts: Sequence[float | None], chain: _Chain):
        self._models = list(models)
        self._timeouts = list(timeouts)
        self._chain = chain

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        now = self._chain.clock()
        ready = [i for i in range(len(self._models)) if self._chain.resting_until[i] <= now]
        # if every model is resting, try them all anyway: a refusal is no worse than not asking
        order = ready or list(range(len(self._models)))
        last = len(order) - 1
        for position, index in enumerate(order):
            timeout = self._timeouts[index] if position < last else None
            try:
                async with asyncio.timeout(timeout):
                    answer: AIMessage = await self._models[index].ainvoke(messages)
                    return answer
            except Exception as error:  # any failure of this model: the next one is asked
                if isinstance(error, openai.RateLimitError):
                    self._chain.resting_until[index] = self._chain.clock() + RATE_LIMIT_PAUSE
                if position == last:
                    raise
        raise RuntimeError("no model to ask")  # not reached: there are always two or more


class FallbackChatModel:
    def __init__(
        self,
        first: Any,
        *backups: Any,
        first_timeout: float = FIRST_TIMEOUT,
        backup_timeout: float = BACKUP_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not backups:
            raise ValueError("a fallback model needs at least one backup")
        self._models = [first, *backups]
        self._timeouts: list[float | None] = [first_timeout, *([backup_timeout] * len(backups))]
        self._chain = _Chain(len(self._models), clock)

    @property
    def model_name(self) -> str | None:
        name = getattr(self._models[0], "model_name", None)
        return str(name) if name is not None else None

    @property
    def model_names(self) -> list[str]:
        return [str(getattr(m, "model_name", "?")) for m in self._models]

    def bind_tools(self, tools: Sequence[Any]) -> _BoundWithBackup:
        return _BoundWithBackup(
            [m.bind_tools(tools) for m in self._models], self._timeouts, self._chain
        )

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        return await _BoundWithBackup(self._models, self._timeouts, self._chain).ainvoke(messages)
