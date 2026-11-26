"""The six real conversations that went wrong (audit 2026-11, Part C7), as regression tests.

The model is a fake that gives the kind of answer that was really observed, so these tests check
what the code guarantees whatever the model writes: the kind of question, the instruction the model
gets, red flags answered without a model, no "it is safe" clearance, and the warnings a treatment
request always carries. What a real model then writes is measured separately (live evaluation),
never claimed here.
"""

from collections.abc import Sequence

from pharmavique.assistant.application.ask import AskAssistant
from pharmavique.assistant.application.ports import AgentRun
from pharmavique.assistant.domain.answers import Citation, Level
from pharmavique.assistant.domain.conversation import Turn
from pharmavique.assistant.domain.triage import (
    HEADACHE_RED_FLAGS_NOTE,
    NO_CLEARANCE_NOTE,
    RED_FLAG_REPLY,
    SYMPTOM_WARNING,
)

DOC = Citation("document:1", "Imigran leaflet", "https://www.sfda.gov.sa/x", "document", None)


class ObservedModel:
    """Answers with a fixed text and records the instruction it was given."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.guidance: list[str] = []

    async def run(
        self,
        question: str,
        level: Level,
        register_number: str | None,
        *,
        spoken: bool = False,
        history: Sequence[Turn] = (),
        guidance: str = "",
    ) -> AgentRun:
        self.guidance.append(guidance)
        return AgentRun(self.text, (DOC,), ("search_documents",))


async def _ask(model: ObservedModel, question: str, history: Sequence[Turn] = ()) -> str:
    answer = await AskAssistant(model).ask(question, Level.PATIENT, None, history=history)
    return answer.text


async def test_1_a_migraine_treatment_request_gets_categories_questions_and_warnings() -> None:
    # observed: Sumatriptan and Rizatriptan recommended at once, nothing asked, no warning
    model = ObservedModel(
        "تقدر تاخد سوماتريبتان أو ريزاتريبتان [1]. الاتنين من التريبتانات وبيستخدموا للصداع "
        "النصفي [1]."
    )

    text = await _ask(model, "I have a migraine. What medicine or active ingredient could help?")

    guidance = model.guidance[0]
    assert "triptans" in guidance
    assert "prescription-only" in guidance
    assert "paracetamol" in guidance
    assert "NSAIDs" in guidance
    assert "pregnancy" in guidance
    assert "other medicines" in guidance
    assert "تقدر تاخد سوماتريبتان" not in text  # "you can take X" without "ask first" is removed
    assert HEADACHE_RED_FLAGS_NOTE in text
    assert text.rstrip().endswith(SYMPTOM_WARNING)


async def test_2_what_each_medicine_is_for_is_answered_without_a_questionnaire() -> None:
    model = ObservedModel("البنادول فيه باراسيتامول، مسكن وخافض حرارة [1].")

    text = await _ask(
        model,
        "Can you tell me what each of these medicines is used for? And what do you think about "
        "Panadol?",
    )

    assert "do not ask about the person's symptoms" in model.guidance[0].lower()
    assert SYMPTOM_WARNING not in text


async def test_3_panadol_with_sumatriptan_never_gets_a_clearance() -> None:
    model = ObservedModel(
        "مفيش تداخل بين البنادول والسوماتريبتان. تقدر تاخدهم مع بعض بأمان بعد ما تسأل الصيدلي. "
        "البنادول فيه باراسيتامول [1]."
    )

    text = await _ask(model, "Can I take Panadol with Sumatriptan?")

    assert "check_interactions" in model.guidance[0]
    assert "مفيش تداخل" not in text
    assert "بأمان" not in text
    assert "البنادول فيه باراسيتامول" in text
    assert NO_CLEARANCE_NOTE in text


async def test_3_what_a_source_records_is_kept() -> None:
    model = ObservedModel(
        "لا يوجد تداخل مسجّل في DDInter بين الباراسيتامول والسوماتريبتان [1]، وهذا ما يعني إنه "
        "آمن لك."
    )

    text = await _ask(model, "ينفع آخد بنادول مع سوماتريبتان؟")

    assert text.startswith("لا يوجد تداخل مسجّل في DDInter")
    assert NO_CLEARANCE_NOTE not in text


async def test_4_what_sumatriptan_is_used_for_is_answered_directly() -> None:
    model = ObservedModel("السوماتريبتان من التريبتانات ويستخدم لعلاج نوبات الصداع النصفي [1].")

    text = await _ask(model, "What is Sumatriptan used for?")

    assert "Answer it directly" in model.guidance[0]
    assert text == "السوماتريبتان من التريبتانات ويستخدم لعلاج نوبات الصداع النصفي [1]."


async def test_5_a_severe_headache_is_not_assumed_to_be_a_migraine() -> None:
    model = ObservedModel("ممكن تسأل الصيدلي عن مسكن فيه باراسيتامول قبل ما تاخذه [1].")

    text = await _ask(model, "I have a severe headache. Recommend a medicine.")

    assert "Do not assume it is a migraine" in model.guidance[0]
    assert HEADACHE_RED_FLAGS_NOTE in text
    assert SYMPTOM_WARNING in text


async def test_5_a_severe_headache_with_a_red_flag_goes_to_urgent_care_without_a_model() -> None:
    model = ObservedModel("خد بنادول")

    answer = await AskAssistant(model).ask(
        "I have a severe headache that came suddenly and my arm is numb. Recommend a medicine.",
        Level.PATIENT,
        None,
    )

    assert answer.text == RED_FLAG_REPLY
    assert answer.urgent is True
    assert answer.outcome == "red_flag"
    assert model.guidance == []  # the model was never asked


async def test_6_heart_disease_gets_no_reassurance() -> None:
    model = ObservedModel("الدواء آمن لمرضى القلب. النشرة تذكر الحذر مع أمراض القلب التاجية [1].")

    text = await _ask(model, "Is this medication safe for someone with heart disease?")

    assert "contraindications" in model.guidance[0]
    assert "الدواء آمن لمرضى القلب" not in text
    assert "النشرة تذكر الحذر" in text
    assert NO_CLEARANCE_NOTE in text


async def test_a_follow_up_answer_to_the_questions_keeps_the_warnings() -> None:
    model = ObservedModel("بما إنك مش حامل، الباراسيتامول من الخيارات اللي تسأل عنها الصيدلي [1].")
    history = (
        Turn("user", "عندي صداع نصفي آخد ايه؟"),
        Turn("assistant", "محتاج أعرف: هل انتي حامل؟ وبتاخدي أدوية تانية؟"),
    )

    text = await _ask(model, "لا مش حامل ومباخدش أدوية تانية", history)

    assert "Egyptian" in model.guidance[0]
    assert SYMPTOM_WARNING in text
