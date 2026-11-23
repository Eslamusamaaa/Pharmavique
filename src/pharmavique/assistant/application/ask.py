"""Ask the assistant a question. Every guardrail runs here, around the model, in this order:

1. emergency in the question -> "call 997" (no model call)
2. manipulation attempt (rules, then the learned detector) -> fixed reply (no model call)
3. the model and its tools
4. empty answer -> "found nothing"
5. personal dose / stop / switch instruction -> replaced
6. a number or register number no tool returned -> withheld (no hallucinated facts)
Each question is recorded for observability, without its text.
"""

import time
from collections.abc import Sequence
from dataclasses import replace

from pharmavique.assistant.application.ports import (
    AgentRun,
    AgentRunner,
    AssistantEvent,
    AssistantObserver,
    InjectionDetector,
)
from pharmavique.assistant.domain.answers import (
    EMERGENCY_REPLY,
    NOT_IN_SOURCES,
    RULE_REFUSAL,
    SOURCES_DOWN,
    Answer,
    Level,
    breaks_rules,
    is_emergency,
    without_rule_breaking_sentences,
    without_unsupported_use_claims,
)
from pharmavique.assistant.domain.conversation import Turn, prepare_history
from pharmavique.assistant.domain.guardrails import (
    INJECTION_REPLY,
    UNGROUNDED_REPLY,
    looks_like_injection,
    ungrounded_facts,
)

MAX_QUESTION = 1000


class AskAssistant:
    def __init__(
        self,
        runner: AgentRunner,
        *,
        detector: InjectionDetector | None = None,
        observer: AssistantObserver | None = None,
    ) -> None:
        self._runner = runner
        self._detector = detector
        self._observer = observer

    async def ask(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
    ) -> Answer:
        """`spoken`: the answer will be read aloud, so it is written in Saudi dialect.
        `history`: the earlier turns of this conversation, as the app kept them."""
        question = question.strip()
        if not question or len(question) > MAX_QUESTION:
            raise ValueError(f"a question must be 1 to {MAX_QUESTION} characters")
        started = time.perf_counter()
        run = AgentRun("", (), ())
        missing: list[str] = []
        try:
            answer, run, missing = await self._answer(
                question, level, register_number, spoken, prepare_history(history)
            )
        except Exception:
            self._record("error", level, spoken, run, started, len(question), 0)
            raise
        self._record(answer.outcome, level, spoken, run, started, len(question), len(missing))
        return answer

    async def _answer(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        spoken: bool,
        history: tuple[Turn, ...],
    ) -> tuple[Answer, AgentRun, list[str]]:
        empty = AgentRun("", (), ())
        if is_emergency(question):
            return (
                Answer(
                    EMERGENCY_REPLY, (), level, grounded=False, urgent=True, outcome="emergency"
                ),
                empty,
                [],
            )
        if looks_like_injection(question) or await self._detected(question):
            return (
                Answer(INJECTION_REPLY, (), level, grounded=False, outcome="injection"),
                empty,
                [],
            )
        run = await self._runner.run(
            question, level, register_number, spoken=spoken, history=history
        )
        text = run.text.strip()
        # A page from the open web is unverified (ADR-017): it is cited, but it is not the registry.
        registry = any(citation.kind != "web" for citation in run.citations)
        base = Answer(
            text,
            run.citations,
            level,
            grounded=registry,
            tools_used=run.tools_used,
            general=not registry,
            outcome="answered" if registry else "web" if run.citations else "general",
        )
        if run.tool_calls and not any(call.ok for call in run.tool_calls):
            # Every lookup failed (database or provider down): an answer now could only come
            # from the model's memory, which is how drugs get misidentified.
            return (
                replace(base, text=SOURCES_DOWN, general=False, outcome="sources_down"),
                run,
                [],
            )
        if not text:
            return replace(base, text=NOT_IN_SOURCES, general=False, outcome="empty"), run, []
        if breaks_rules(text):
            # Remove only the sentences that give a dose or say to stop or switch; keep the rest.
            cleaned = without_rule_breaking_sentences(text)
            if cleaned is None:
                return (
                    replace(
                        base,
                        text=RULE_REFUSAL,
                        refused=True,
                        general=False,
                        outcome="rule_refusal",
                    ),
                    run,
                    [],
                )
            text = cleaned
            base = replace(base, text=cleaned)
        if not any(c.kind in ("document", "web") for c in run.citations):
            # nothing retrieved says what a medicine is for: a "used for" sentence is memory
            unsupported = without_unsupported_use_claims(text)
            if unsupported is not None and unsupported != text:
                text = unsupported
                base = replace(base, text=unsupported)
        # Numbers from earlier answers in this conversation count as known, so a follow-up
        # that repeats them is not withheld.
        missing = ungrounded_facts(
            text, (*run.evidence, question, *(turn.text for turn in history))
        )
        if missing:
            return (
                replace(
                    base, text=UNGROUNDED_REPLY, refused=True, general=False, outcome="ungrounded"
                ),
                run,
                missing,
            )
        return base, run, []

    async def _detected(self, question: str) -> bool:
        if self._detector is None:
            return False
        try:
            return await self._detector.is_injection(question)
        except Exception:
            return False

    def _record(
        self,
        outcome: str,
        level: Level,
        spoken: bool,
        run: AgentRun,
        started: float,
        question_chars: int,
        ungrounded: int,
    ) -> None:
        if self._observer is None:
            return
        self._observer.record(
            AssistantEvent(
                outcome=outcome,
                level=level.value,
                spoken=spoken,
                tool_calls=tuple(call.name for call in run.tool_calls) or run.tools_used,
                tool_errors=sum(1 for call in run.tool_calls if not call.ok),
                latency_ms=int((time.perf_counter() - started) * 1000),
                model=run.model,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                citations=len(run.citations),
                question_chars=question_chars,
                ungrounded_facts=ungrounded,
            )
        )
