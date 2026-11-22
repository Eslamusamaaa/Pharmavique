"""The chat model for Cloudflare Workers AI's OpenAI-compatible endpoint.

It is the standard LangChain `ChatOpenAI` with one fix. OpenAI's format sends `content: null` on an
assistant message that only carries a tool call; Cloudflare answers HTTP 400 ("string not in
null") to that, so on the second turn of every tool-using answer the backup would fail. An empty
string is sent instead.
"""

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_openai import ChatOpenAI


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
