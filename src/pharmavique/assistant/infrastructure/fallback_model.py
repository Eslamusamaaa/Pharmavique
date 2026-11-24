"""A chat model with a backup, for the free plans' limits.

The first model is Groq's `gpt-oss-120b`, whose free plan allows 8,000 tokens a minute: one answer
takes most of that, so a second question in the same minute is refused. When the first model is
rate limited, too slow or unreachable, the same call goes to the backup (the same model on
Cloudflare Workers AI), so a person gets an answer instead of waiting for the limit to reset.
Both are LangChain chat models with `bind_tools`.
"""

import asyncio
from collections.abc import Sequence
from typing import Any

import openai
from langchain_core.messages import AIMessage, BaseMessage

FIRST_TIMEOUT = 25.0  # seconds before the backup is tried
_FALLBACK_ON = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError)
# 413: Groq's free plan refuses a request bigger than its tokens-per-minute limit (a long question
# with long tool results); 5xx: the provider failed. The backup has other limits, so it is tried.
_FALLBACK_STATUS = frozenset({413, 500, 502, 503, 504})


def _worth_the_backup(error: BaseException) -> bool:
    if isinstance(error, (*_FALLBACK_ON, TimeoutError)):
        return True
    return isinstance(error, openai.APIStatusError) and error.status_code in _FALLBACK_STATUS


class _BoundWithBackup:
    def __init__(self, first: Any, backup: Any, first_timeout: float) -> None:
        self._first = first
        self._backup = backup
        self._first_timeout = first_timeout

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        try:
            async with asyncio.timeout(self._first_timeout):
                answer: AIMessage = await self._first.ainvoke(messages)
                return answer
        except (openai.APIError, TimeoutError) as error:
            if not _worth_the_backup(error):
                raise
            backup_answer: AIMessage = await self._backup.ainvoke(messages)
            return backup_answer


class FallbackChatModel:
    def __init__(self, first: Any, backup: Any, first_timeout: float = FIRST_TIMEOUT) -> None:
        self._first = first
        self._backup = backup
        self._first_timeout = first_timeout

    @property
    def model_name(self) -> str | None:
        name = getattr(self._first, "model_name", None)
        return str(name) if name is not None else None

    def bind_tools(self, tools: Sequence[Any]) -> _BoundWithBackup:
        return _BoundWithBackup(
            self._first.bind_tools(tools), self._backup.bind_tools(tools), self._first_timeout
        )

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        return await _BoundWithBackup(self._first, self._backup, self._first_timeout).ainvoke(
            messages
        )
