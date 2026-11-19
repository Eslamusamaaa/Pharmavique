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
    Answer,
    Level,
    breaks_rules,
    is_emergency,
)
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
        self, question: str, level: Level, register_number: str | None, *, spoken: bool = False
    ) -> Answer:
        """`spoken`: the answer will be read aloud, so it is written in Saudi dialect."""
        question = question.strip()
        if not question or len(question) > MAX_QUESTION:
            raise ValueError(f"a question must be 1 to {MAX_QUESTION} characters")
        started = time.perf_counter()
        run = AgentRun("", (), ())
        missing: list[str] = []
        try:
            answer, run, missing = await self._answer(question, level, register_number, spoken)
        except Exception:
            self._record("error", level, spoken, run, started, len(question), 0)
            raise
        self._record(answer.outcome, level, spoken, run, started, len(question), len(missing))
        return answer

    async def _answer(
        self, question: str, level: Level, register_number: str | None, spoken: bool
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
        run = await self._runner.run(question, level, register_number, spoken=spoken)
        text = run.text.strip()
        base = Answer(
            text,
            run.citations,
            level,
            grounded=bool(run.citations),
            tools_used=run.tools_used,
            general=not run.citations,
            outcome="answered" if run.citations else "general",
        )
        if not text:
            return replace(base, text=NOT_IN_SOURCES, general=False, outcome="empty"), run, []
        if breaks_rules(text):
            return (
                replace(
                    base, text=RULE_REFUSAL, refused=True, general=False, outcome="rule_refusal"
                ),
                run,
                [],
            )
        missing = ungrounded_facts(text, (*run.evidence, question))
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
