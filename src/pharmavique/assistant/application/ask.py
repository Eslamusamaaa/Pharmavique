"""Ask the assistant a question. The response policy is enforced here, around the model."""

from pharmavique.assistant.application.ports import AgentRunner
from pharmavique.assistant.domain.answers import (
    EMERGENCY_REPLY,
    NOT_IN_SOURCES,
    RULE_REFUSAL,
    Answer,
    Level,
    breaks_rules,
    is_emergency,
)

MAX_QUESTION = 1000


class AskAssistant:
    def __init__(self, runner: AgentRunner) -> None:
        self._runner = runner

    async def ask(
        self, question: str, level: Level, register_number: str | None, *, spoken: bool = False
    ) -> Answer:
        """`spoken`: the answer will be read aloud, so it is written in Saudi dialect."""
        question = question.strip()
        if not question or len(question) > MAX_QUESTION:
            raise ValueError(f"a question must be 1 to {MAX_QUESTION} characters")
        if is_emergency(question):
            return Answer(EMERGENCY_REPLY, (), level, grounded=False, urgent=True)
        run = await self._runner.run(question, level, register_number, spoken=spoken)
        text = run.text.strip()
        if not text:
            return Answer(NOT_IN_SOURCES, (), level, grounded=False, tools_used=run.tools_used)
        if breaks_rules(text):
            return Answer(
                RULE_REFUSAL,
                run.citations,
                level,
                grounded=bool(run.citations),
                refused=True,
                tools_used=run.tools_used,
            )
        return Answer(
            text,
            run.citations,
            level,
            grounded=bool(run.citations),
            tools_used=run.tools_used,
            general=not run.citations,
        )
