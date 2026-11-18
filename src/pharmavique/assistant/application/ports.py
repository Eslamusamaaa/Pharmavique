"""Ports of the assistant (ADR-005, ADR-007): the agent runner and the facts its tools read.

The agent framework (LangGraph) lives only in `infrastructure`. Tools read other contexts through
`DrugFacts`, which the composition root implements over their published contracts.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pharmavique.assistant.domain.answers import Citation, Level


@dataclass(frozen=True, slots=True)
class AgentRun:
    text: str
    citations: tuple[Citation, ...]  # every record a tool returned and the model may cite
    tools_used: tuple[str, ...]


class AgentRunner(Protocol):
    async def run(
        self, question: str, level: Level, register_number: str | None, *, spoken: bool = False
    ) -> AgentRun: ...


class DrugFacts(Protocol):
    """Read-only facts for the tools, as plain JSON-ready values with their sources."""

    async def search_drugs(self, query: str, limit: int) -> list[dict[str, Any]]: ...

    async def drug_details(self, register_number: str) -> dict[str, Any] | None: ...

    async def same_ingredient(self, register_number: str, limit: int) -> list[dict[str, Any]]: ...

    async def documents(
        self, query: str, register_numbers: Sequence[str], limit: int
    ) -> list[dict[str, Any]]: ...
