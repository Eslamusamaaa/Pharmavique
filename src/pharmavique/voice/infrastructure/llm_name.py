"""Drug-name extraction with the same chat model the assistant uses (no tools, one short call)."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

PROMPT = (
    "You extract the medicine name from what a person said when they searched for a drug "
    "(Arabic, Saudi or Egyptian dialect, or English). Reply with the medicine name only: the brand "
    "name or active ingredient exactly as spoken, in the language it was spoken, with its strength "
    "if they said one. No explanation, no quotes. If no medicine is named, reply NONE."
)


class LlmDrugNameExtractor:
    def __init__(self, model: Any) -> None:
        self._model = model

    async def extract(self, text: str) -> str | None:
        reply = await self._model.ainvoke([SystemMessage(PROMPT), HumanMessage(text)])
        content = reply.content
        if isinstance(content, str):
            return content
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
