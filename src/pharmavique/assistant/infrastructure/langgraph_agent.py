"""`AgentRunner` built with LangGraph (ADR-007): a model node and a tool node in a loop.

Tools read facts through the `DrugFacts` port. Every record a tool returns gets a citation number;
the model cites by number and the runner returns the cited records, so a citation always points at
something that was really retrieved. The model is any LangChain chat model with tool binding
(OpenAI-compatible: Groq or OpenRouter), chosen by configuration.
"""

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from pharmavique.assistant.application.ports import AgentRun, DrugFacts
from pharmavique.assistant.domain.answers import Citation, Level
from pharmavique.assistant.infrastructure.prompts import system_prompt

MAX_STEPS = 12  # graph steps: model and tool turns together
NUDGE = (
    "Write the final answer to my question now, from the tool results above, "
    "citing each fact with its [n]. If they do not answer it, say it is not in our sources."
)
_CITED = re.compile(r"[\[【](\d+)[\]】]")  # some models write 【n】 instead of [n]


class _Citations:
    """Numbers each retrieved record once, in the order the tools returned them."""

    def __init__(self) -> None:
        self.items: list[Citation] = []
        self._numbers: dict[str, int] = {}

    def number(self, citation: Citation) -> int:
        if citation.source_id not in self._numbers:
            self.items.append(citation)
            self._numbers[citation.source_id] = len(self.items)
        return self._numbers[citation.source_id]


def _drug_citation(record: dict[str, Any]) -> Citation:
    number = str(record.get("register_number"))
    name = record.get("trade_name_ar") or record.get("trade_name_en") or number
    return Citation(
        f"catalog:{number}",
        f"{name} · سجل الأدوية (SFDA)",
        record.get("source_ref") or "https://www.sfda.gov.sa/en/drugs-list",
        "catalog",
        None,
    )


def _document_citation(record: dict[str, Any]) -> Citation:
    return Citation(
        f"document:{record.get('chunk_id')}",
        str(record.get("title") or "مستند رسمي"),
        record.get("source_ref"),
        "document",
        record.get("published"),
    )


def build_tools(facts: DrugFacts, citations: _Citations, used: list[str]) -> list[BaseTool]:
    def cite(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        maker = _drug_citation if kind == "catalog" else _document_citation
        return [{"cite": citations.number(maker(r)), **r} for r in records]

    async def search_drugs(query: str) -> str:
        """Find registered drugs by trade name, active ingredient or register number (Arabic or
        English, misspellings allowed). Returns up to 8 products with their register numbers."""
        used.append("search_drugs")
        return json.dumps(cite(await facts.search_drugs(query, 8), "catalog"), ensure_ascii=False)

    async def drug_details(register_number: str) -> str:
        """Every registry field of one product: ingredients and strengths, dosage form, route,
        package, legal status, ATC, storage, company, manufacturers and registered price."""
        used.append("drug_details")
        record = await facts.drug_details(register_number)
        if record is None:
            return json.dumps({"error": "no such register number"})
        return json.dumps(cite([record], "catalog")[0], ensure_ascii=False)

    async def same_ingredient(register_number: str) -> str:
        """Products with the same active ingredients, cheapest first, each with the verdict
        computed by Pharmavique's rules (equivalent / possible_needs_pharmacist_check /
        not_equivalent)."""
        used.append("same_ingredient")
        rows = await facts.same_ingredient(register_number, 15)
        return json.dumps(cite(rows, "catalog"), ensure_ascii=False)

    async def search_documents(query: str, register_number: str = "") -> str:
        """Search official SFDA documents (safety alerts, DHPC letters, recalls and circulars,
        labeling updates, risk minimization materials). Optionally limit to one product."""
        used.append("search_documents")
        numbers = [register_number] if register_number else []
        rows = await facts.documents(query, numbers, 6)
        return json.dumps(cite(rows, "document"), ensure_ascii=False)

    functions = (search_drugs, drug_details, same_ingredient, search_documents)
    return [StructuredTool.from_function(coroutine=f, name=f.__name__) for f in functions]


def _final_text(messages: Sequence[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            content = message.content
            if isinstance(content, str):
                return content
            return "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
    return ""


class LangGraphAgentRunner:
    """Implements `AgentRunner`. `model` is a LangChain chat model that supports `bind_tools`."""

    def __init__(self, model: Any, facts: DrugFacts) -> None:
        self._model = model
        self._facts = facts

    async def run(
        self, question: str, level: Level, register_number: str | None, *, spoken: bool = False
    ) -> AgentRun:
        citations = _Citations()
        used: list[str] = []
        tools = build_tools(self._facts, citations, used)
        bound = self._model.bind_tools(tools)
        prompt = SystemMessage(system_prompt(level, register_number, spoken=spoken))

        async def call_model(state: MessagesState) -> dict[str, list[BaseMessage]]:
            return {"messages": [await bound.ainvoke([prompt, *state["messages"]])]}

        graph = StateGraph(MessagesState)
        graph.add_node("model", call_model)
        graph.add_node("tools", ToolNode(tools))
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
        graph.add_edge("tools", "model")
        app = graph.compile()
        result = await app.ainvoke(
            {"messages": [HumanMessage(question)]}, {"recursion_limit": MAX_STEPS}
        )
        text = _final_text(result["messages"])
        if not text.strip():
            # Reasoning models sometimes end a turn with no visible text: ask once for the answer.
            result = await app.ainvoke(
                {"messages": [*result["messages"], HumanMessage(NUDGE)]},
                {"recursion_limit": MAX_STEPS},
            )
            text = _final_text(result["messages"])
        # Keep only records the answer cites and that really exist, renumbered 1..n in that order.
        cited = sorted(
            {int(n) for n in _CITED.findall(text) if 1 <= int(n) <= len(citations.items)}
        )
        renumber = {old: new for new, old in enumerate(cited, start=1)}
        text = _CITED.sub(
            lambda m: f"[{renumber[int(m.group(1))]}]" if int(m.group(1)) in renumber else "",
            text,
        )
        chosen = tuple(citations.items[old - 1] for old in cited)
        return AgentRun(text, chosen, tuple(dict.fromkeys(used)))
