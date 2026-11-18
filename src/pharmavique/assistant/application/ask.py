"""Ask the assistant a question. The rules are enforced after the model, never
trusted to it.
"""

from pharmavique.assistant.application.ports import AgentRunner
from pharmavique.assistant.domain.answers import (
    NOT_IN_SOURCES,
    RULE_REFUSAL,
    Answer,
    Level,
    breaks_rules,
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
        run = await self._runner.run(question, level, register_number, spoken=spoken)
        if not run.citations:
            return Answer(NOT_IN_SOURCES, (), level, grounded=False, tools_used=run.tools_used)
        if breaks_rules(run.text):
            return Answer(
                RULE_REFUSAL,
                run.citations,
                level,
                grounded=True,
                refused=True,
                tools_used=run.tools_used,
            )
        return Answer(
            run.text.strip(), run.citations, level, grounded=True, tools_used=run.tools_used
        )
