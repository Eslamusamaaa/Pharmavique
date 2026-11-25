"""The chat model for Cloudflare Workers AI's OpenAI-compatible endpoint.

It is the standard LangChain `ChatOpenAI` with one fix. OpenAI's format sends `content: null` on an
assistant message that only carries a tool call; Cloudflare answers HTTP 400 ("string not in
null") to that, so on the second turn of every tool-using answer the backup would fail. An empty
string is sent instead.

Gemma 4 runs with thinking switched off (much faster); once it still began its reply with the name
of its thinking channel ("thought") and nothing else. That marker is removed from the start of a
reply, so the runner sees an empty answer and asks again instead of showing the word.
"""

import re
from typing import Any

import openai
from langchain_core.language_models import LanguageModelInput
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI

_THINKING_MARKER = re.compile(r"^\s*(?:<\|channel\|?>)?thought(?:[ \t]*\n\s*|\s*$)")


class CloudflareChatOpenAI(ChatOpenAI):
    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message in payload.get("messages", []):
            if isinstance(message, dict) and message.get("content") is None:
                message["content"] = ""
        return payload

    def _create_chat_result(
        self,
        response: dict[str, Any] | openai.BaseModel,
        generation_info: dict[str, Any] | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        for generation in result.generations:
            message = generation.message
            if isinstance(message.content, str):
                message.content = _THINKING_MARKER.sub("", message.content, count=1)
        return result
