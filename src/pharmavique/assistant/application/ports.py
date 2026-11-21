"""Ports of the assistant (ADR-005, ADR-007): the agent runner, the facts its tools read, the
injection detector and the observer.

The agent framework (LangGraph) lives only in `infrastructure`. Tools read other contexts through
`DrugFacts`, which the composition root implements over their published contracts.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pharmavique.assistant.domain.answers import Citation, Level
from pharmavique.assistant.domain.conversation import Turn


class AssistantBusy(Exception):
    """The model provider refused the call for now (rate limit): the app should retry shortly."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    ok: bool
    duration_ms: int
    results: int  # records returned (0 on error)


@dataclass(frozen=True, slots=True)
class AgentRun:
    text: str
    citations: tuple[Citation, ...]  # the records the answer cites
    tools_used: tuple[str, ...]
    evidence: tuple[str, ...] = ()  # everything the tools returned in this run, as text
    tool_calls: tuple[ToolCall, ...] = ()
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class AgentRunner(Protocol):
    async def run(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
    ) -> AgentRun:
        """`history`: earlier turns of this conversation, already cleaned."""
        ...


class DrugFacts(Protocol):
    """Read-only facts for the tools, as plain JSON-ready values with their sources."""

    async def search_drugs(self, query: str, limit: int) -> list[dict[str, Any]]: ...

    async def drug_details(self, register_number: str) -> dict[str, Any] | None: ...

    async def same_ingredient(self, register_number: str, limit: int) -> list[dict[str, Any]]: ...

    async def documents(
        self, query: str, register_numbers: Sequence[str], limit: int
    ) -> list[dict[str, Any]]: ...

    async def contraindications(self, register_number: str) -> list[dict[str, Any]]:
        """Conditions the product's ingredients are recorded as contraindicated with (source and
        label text each), then one `coverage` record: a missing record is never a clearance."""
        ...

    async def check_interactions(self, register_numbers: Sequence[str]) -> list[dict[str, Any]]:
        """Recorded interactions and duplicated ingredients among these products, each with its
        source, then one `coverage` record naming the ingredients the source cannot judge."""
        ...


class InjectionDetector(Protocol):
    """A learned classifier for manipulation attempts; it adds to the rules, never replaces them."""

    async def is_injection(self, text: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AssistantEvent:
    """What is recorded about one question. Never the question or the answer text (health data)."""

    outcome: str  # answered, general, emergency, injection, rule_refusal, ungrounded, empty, error
    level: str
    spoken: bool
    tool_calls: tuple[str, ...]
    tool_errors: int
    latency_ms: int
    model: str | None
    input_tokens: int
    output_tokens: int
    citations: int
    question_chars: int
    ungrounded_facts: int = 0


class AssistantObserver(Protocol):
    def record(self, event: AssistantEvent) -> None: ...
