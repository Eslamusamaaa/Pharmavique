"""The assistant's response policy (owner, 2026-11-19): helpful by default, firm only on danger.

- Registry facts come from tools with citations; general information is allowed and labelled.
- Hard limits: no personal dose numbers, no telling someone to stop or switch a medicine on their
  own (consulting a doctor first is fine), emergencies get an immediate "call 997" reply.
"""

from typing import ClassVar

import pytest

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AgentRun
from pharmavique.assistant.domain.answers import (
    EMERGENCY_REPLY,
    NOT_IN_SOURCES,
    RULE_REFUSAL,
    Citation,
    Level,
    breaks_rules,
    is_emergency,
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


async def test_a_general_answer_without_a_source_is_kept_and_labelled_general() -> None:
    text = "أيوه، البنادول مسكن متاح بدون وصفة، ولو عندك مشكلة في الكبد اسأل الصيدلي."

    answer = await AskAssistant(FakeRunner(text, ())).ask("ينفع آخد بنادول؟", Level.PATIENT, None)

    assert answer.text == text
    assert answer.grounded is False
    assert answer.general is True


async def test_an_empty_model_answer_says_it_found_nothing() -> None:
    answer = await AskAssistant(FakeRunner("  ", ())).ask("x", Level.PATIENT, None)

    assert answer.text == NOT_IN_SOURCES
    assert answer.general is False


@pytest.mark.parametrize(
    "question",
    [
        "بلعت علبة بنادول كاملة",
        "ابني بلع شريط بنادول كامل",
        "بنتي شربت نص زجاجة الشراب",
        "ابني شرب الشراب كله بالغلط",
        "عندي ضيق تنفس وتورم في وشي بعد الدوا",
        "I took an overdose of my pills",
        "عايز أموت",
    ],
)
def test_emergencies_are_recognised(question: str) -> None:
    assert is_emergency(question)


@pytest.mark.parametrize(
    "question", ["ينفع آخد بنادول؟", "ايه الفرق بين بنادول وبنادول اكسترا؟", "سعره كام؟"]
)
def test_ordinary_questions_are_not_emergencies(question: str) -> None:
    assert not is_emergency(question)


async def test_an_emergency_gets_the_emergency_reply_without_a_model_call() -> None:
    runner = FakeRunner("x")

    answer = await AskAssistant(runner).ask("بلعت علبة بنادول كاملة", Level.PATIENT, None)

    assert answer.text == EMERGENCY_REPLY
    assert answer.urgent is True
    assert "997" in answer.text
    assert runner.seen == []


@pytest.mark.parametrize(
    "text",
    [
        "توقف عن تناول دواء الضغط فورًا",
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
        "متوقفش عن أي دواء موصوف لك قبل ما تسأل دكتورك.",
        "لو حصل لك طفح جلدي شديد، توقف عن تناوله واتصل بالطبيب فورًا.",
        "Ask your doctor before you stop taking it.",
        "مفيش موانع عامة، بس لو عندك مرض مزمن اسأل الصيدلي.",
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
