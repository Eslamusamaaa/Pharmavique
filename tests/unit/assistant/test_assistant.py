"""The assistant's rules: answers only from cited sources, no dosing, never "stop" or "switch"."""

from typing import ClassVar

import pytest

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AgentRun
from pharmavique.assistant.domain.answers import (
    NOT_IN_SOURCES,
    RULE_REFUSAL,
    Citation,
    Level,
    breaks_rules,
)

CITE = Citation("catalog:1-1", "بانادول 500 ملجم", "https://www.sfda.gov.sa/x", "catalog", None)


class FakeRunner:
    def __init__(self, text: str, citations: tuple[Citation, ...] = (CITE,)) -> None:
        self.result = AgentRun(text, citations, ("drug_details",))
        self.seen: list[tuple[str, Level, str | None]] = []

    async def run(
        self, question: str, level: Level, register_number: str | None, *, spoken: bool = False
    ) -> AgentRun:
        self.seen.append((question, level, register_number))
        return self.result


async def test_a_grounded_answer_is_returned_with_its_citations() -> None:
    runner = FakeRunner("المادة الفعالة هي الباراسيتامول [1].")

    answer = await AskAssistant(runner).ask("ايه المادة الفعالة؟", Level.PATIENT, "1-1")

    assert answer.text == "المادة الفعالة هي الباراسيتامول [1]."
    assert answer.citations == (CITE,)
    assert answer.grounded is True
    assert runner.seen == [("ايه المادة الفعالة؟", Level.PATIENT, "1-1")]


async def test_an_answer_without_any_source_says_so_instead_of_guessing() -> None:
    answer = await AskAssistant(FakeRunner("It treats headaches.", ())).ask(
        "what is it for?", Level.PATIENT, None
    )

    assert answer.text == NOT_IN_SOURCES
    assert answer.grounded is False


@pytest.mark.parametrize(
    "text",
    [
        "توقف عن تناول الدواء فورًا",
        "استبدله ببانادول",
        "خذ قرصين 3 مرات يوميا",
        "Take 500 mg twice a day",
        "You should stop taking it",
        "switch to ibuprofen",
    ],
)
def test_dosing_stop_and_switch_instructions_break_the_rules(text: str) -> None:
    assert breaks_rules(text)


@pytest.mark.parametrize(
    "text",
    [
        "المادة الفعالة هي الباراسيتامول بتركيز 500 ملجم.",
        "يوجد منتجات بنفس المادة الفعالة؛ الصيدلي يقرر إن كانت مناسبة لك.",
        "The registered strength is 500 mg.",
    ],
)
def test_facts_about_the_product_are_allowed(text: str) -> None:
    assert not breaks_rules(text)


async def test_an_answer_that_breaks_the_rules_is_replaced_not_shown() -> None:
    answer = await AskAssistant(FakeRunner("خذ قرصين كل 6 ساعات")).ask("x", Level.PATIENT, None)

    assert answer.text == RULE_REFUSAL
    assert answer.refused is True


async def test_an_empty_question_is_refused_before_any_model_call() -> None:
    runner = FakeRunner("x")

    with pytest.raises(ValueError, match="question"):
        await AskAssistant(runner).ask("   ", Level.PATIENT, None)
    assert runner.seen == []


async def test_the_spoken_choice_reaches_the_runner() -> None:
    class Recording(FakeRunner):
        spoken: ClassVar[list[bool]] = []

        async def run(
            self, question: str, level: Level, register_number: str | None, *, spoken: bool = False
        ) -> AgentRun:
            self.spoken.append(spoken)
            return self.result

    runner = Recording("الباراسيتامول [1].")

    await AskAssistant(runner).ask("سؤال", Level.PATIENT, None, spoken=True)

    assert runner.spoken == [True]
