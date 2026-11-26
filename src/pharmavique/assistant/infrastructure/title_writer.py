"""A short title for a saved conversation, written by the chat model (ADR-022).

The model sees only the first question and the start of its answer, and answers with a few
words. Any failure (no model, a timeout, an empty or odd reply) gives `None`, and the conversation
keeps the title cut from its first question. The domain cleans the reply and cuts it to length
before it is stored, so a question that tries to steer the model can at worst give an odd title.
"""

import asyncio
import logging
from typing import Any

TIMEOUT_SECONDS = 15.0
_ANSWER_CHARS = 600
_REPLY_CHARS = 120
_PROMPT = (
    "اكتب عنوانًا قصيرًا من كلمتين إلى ست كلمات يلخص موضوع هذه المحادثة عن دواء، بلغة السؤال نفسها. "
    "اكتب العنوان فقط، بدون علامات تنصيص ولا نقطة في آخره ولا أي شرح."
)
_log = logging.getLogger(__name__)


class ModelTitleWriter:
    def __init__(self, model: Any | None) -> None:
        self._model = model

    async def title(self, question: str, answer: str) -> str | None:
        if self._model is None:
            return None
        # imported here: the API must start without the model libraries (cold starts)
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(_PROMPT),
            HumanMessage(f"السؤال: {question}\n\nبداية الإجابة: {answer[:_ANSWER_CHARS]}"),  # noqa: RUF001
        ]
        try:
            reply = await asyncio.wait_for(self._model.ainvoke(messages), TIMEOUT_SECONDS)
        except Exception as error:
            _log.warning("title model failed", extra={"error": type(error).__name__})
            return None
        text = reply.content if isinstance(reply.content, str) else ""
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        return first_line[:_REPLY_CHARS] or None
