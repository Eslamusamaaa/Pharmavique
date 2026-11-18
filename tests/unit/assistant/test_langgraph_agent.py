"""The LangGraph runner with a scripted model: tools run, citations are numbered and kept."""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.infrastructure.langgraph_agent import LangGraphAgentRunner


class FakeFacts:
    async def search_drugs(self, query: str, limit: int) -> list[dict[str, Any]]:
        return [{"register_number": "1-1", "trade_name_ar": "بانادول", "source_ref": "https://s/1"}]

    async def drug_details(self, register_number: str) -> dict[str, Any] | None:
        if register_number != "1-1":
            return None
        return {
            "register_number": "1-1",
            "trade_name_ar": "بانادول",
            "ingredients": ["PARACETAMOL"],
        }

    async def same_ingredient(self, register_number: str, limit: int) -> list[dict[str, Any]]:
        return []

    async def documents(
        self, query: str, register_numbers: Sequence[str], limit: int
    ) -> list[dict[str, Any]]:
        return [{"chunk_id": "c9", "title": "DHPC", "text": "...", "source_ref": "https://s/d"}]


class ScriptedModel:
    """Plays back AI messages; records what the model was shown."""

    def __init__(self, *replies: AIMessage) -> None:
        self.replies = list(replies)
        self.seen: list[list[BaseMessage]] = []
        self.tools: list[str] = []

    def bind_tools(self, tools: Sequence[Any]) -> "ScriptedModel":
        self.tools = [t.name for t in tools]
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.seen.append(list(messages))
        return self.replies.pop(0)


def call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])


async def test_the_runner_calls_tools_and_keeps_only_the_cited_records() -> None:
    model = ScriptedModel(
        call("drug_details", {"register_number": "1-1"}, "a"),
        call("search_documents", {"query": "تحذير", "register_number": "1-1"}, "b"),
        AIMessage("المادة الفعالة هي الباراسيتامول [1]."),
    )

    run = await LangGraphAgentRunner(model, FakeFacts()).run(
        "ايه المادة الفعالة؟", Level.PATIENT, "1-1"
    )

    assert run.text == "المادة الفعالة هي الباراسيتامول [1]."
    assert [c.source_id for c in run.citations] == ["catalog:1-1"]
    assert run.tools_used == ("drug_details", "search_documents")
    assert model.tools == ["search_drugs", "drug_details", "same_ingredient", "search_documents"]
    tool_results = [m for m in model.seen[-1] if isinstance(m, ToolMessage)]
    assert '"cite": 1' in tool_results[0].content
    assert '"cite": 2' in tool_results[1].content


async def test_the_system_prompt_carries_the_level_and_the_product() -> None:
    model = ScriptedModel(AIMessage("مش في مصادرنا."))

    run = await LangGraphAgentRunner(model, FakeFacts()).run("سؤال", Level.PHARMACIST, "1-1")

    system = model.seen[0][0].content
    assert "pharmacist" in system
    assert "1-1" in system
    assert "Never give a personal dose" in system
    assert "997" in system
    assert run.citations == ()


async def test_full_width_citation_brackets_count_and_are_normalized() -> None:
    model = ScriptedModel(
        call("drug_details", {"register_number": "1-1"}, "a"),
        AIMessage("المادة الفعالة هي الباراسيتامول【1】 وأي رقم مش موجود يتشال【7】."),
    )

    run = await LangGraphAgentRunner(model, FakeFacts()).run("سؤال", Level.PATIENT, None)

    assert run.text == "المادة الفعالة هي الباراسيتامول[1] وأي رقم مش موجود يتشال."
    assert [c.source_id for c in run.citations] == ["catalog:1-1"]


async def test_an_empty_final_reply_gets_one_nudge_to_write_the_answer() -> None:
    model = ScriptedModel(
        call("drug_details", {"register_number": "1-1"}, "a"),
        AIMessage(""),
        AIMessage("المادة الفعالة هي الباراسيتامول [1]."),
    )

    run = await LangGraphAgentRunner(model, FakeFacts()).run("سؤال", Level.PATIENT, None)

    assert run.text == "المادة الفعالة هي الباراسيتامول [1]."
    assert [c.source_id for c in run.citations] == ["catalog:1-1"]


async def test_a_model_that_stays_silent_ends_with_an_empty_answer() -> None:
    model = ScriptedModel(AIMessage(""), AIMessage(""))

    run = await LangGraphAgentRunner(model, FakeFacts()).run("سؤال", Level.PATIENT, None)

    assert run.text == ""


async def test_a_spoken_answer_is_asked_for_in_saudi_dialect() -> None:
    model = ScriptedModel(AIMessage("x"))

    await LangGraphAgentRunner(model, FakeFacts()).run("سؤال", Level.PATIENT, None, spoken=True)

    assert "Saudi dialect" in model.seen[0][0].content
