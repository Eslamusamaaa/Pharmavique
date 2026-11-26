"""The model-written conversation title: the first line of the reply, or None on any failure."""

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from pharmavique.assistant.infrastructure import title_writer
from pharmavique.assistant.infrastructure.title_writer import ModelTitleWriter


class FakeModel:
    def __init__(self, reply: str | Exception, delay: float = 0.0) -> None:
        self.reply = reply
        self.delay = delay
        self.seen: list[Sequence[BaseMessage]] = []

    async def ainvoke(self, messages: Sequence[BaseMessage]) -> Any:
        self.seen.append(messages)
        await asyncio.sleep(self.delay)
        if isinstance(self.reply, Exception):
            raise self.reply
        return AIMessage(self.reply)


async def test_the_first_line_of_the_reply_is_the_title() -> None:
    model = FakeModel("مقارنة بنادول واكسترا\nشرح إضافي")

    assert await ModelTitleWriter(model).title("سؤال", "جواب " * 500) == "مقارنة بنادول واكسترا"
    sent = str(model.seen[0][1].content)
    assert "سؤال" in sent
    assert len(sent) < 700  # only the start of the answer is sent


@pytest.mark.parametrize("reply", ["", "   ", RuntimeError("quota")])
async def test_an_empty_reply_or_a_failure_gives_no_title(reply: str | Exception) -> None:
    assert await ModelTitleWriter(FakeModel(reply)).title("سؤال", "جواب") is None


async def test_no_model_or_a_slow_model_gives_no_title(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(title_writer, "TIMEOUT_SECONDS", 0.01)

    assert await ModelTitleWriter(None).title("سؤال", "جواب") is None
    assert await ModelTitleWriter(FakeModel("عنوان", delay=1)).title("سؤال", "جواب") is None
