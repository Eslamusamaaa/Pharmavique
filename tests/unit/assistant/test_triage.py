"""Triage of a question before the model sees it (audit 2026-11, Part C): what kind of question it
is, red flags that need urgent care, and the dialect to answer in. Pure rules, no model."""

import pytest

from pharmavique.assistant.domain.triage import Dialect, Intent, classify


@pytest.mark.parametrize(
    "question",
    [
        "What is Panadol used for?",
        "What is the active ingredient in Imigran?",
        "What is the difference between Sumatriptan and Rizatriptan?",
        "What are the side effects of Ibuprofen?",
        "ايه استخدام البنادول؟",
        "السوماتريبتان بيستخدم لإيه؟",
        "وش المادة الفعالة في ايميجران؟",
        "ايه الفرق بين سوماتريبتان وريزاتريبتان",
        "Can you tell me what each of these medicines is used for? "
        "And what do you think about Panadol?",
    ],
)
def test_general_drug_questions_are_drug_information(question: str) -> None:
    assert classify(question).intent is Intent.DRUG_INFO


@pytest.mark.parametrize(
    "question",
    [
        "I have a migraine. What medicine or active ingredient could help?",
        "I have stomach pain. What can help?",
        "What can I take for allergies?",
        "I have a severe headache. Recommend a medicine.",
        "عندي صداع نصفي، آخد إيه؟",
        "عندي مغص ايش اخذ",
        "رشحلي دوا للكحة",
        "عندي صداع جامد عايز دوا",
    ],
)
def test_asking_what_to_take_for_a_symptom_is_a_treatment_request(question: str) -> None:
    assert classify(question).intent is Intent.SYMPTOM_TREATMENT


def test_a_headache_treatment_request_knows_its_symptom() -> None:
    assert "headache" in classify("I have a severe headache. Recommend a medicine.").symptoms
    assert "headache" in classify("عندي شقيقة آخد ايه").symptoms


@pytest.mark.parametrize(
    "question",
    [
        "Can I take Panadol with Sumatriptan?",
        "ينفع آخد بنادول مع سوماتريبتان؟",
        "هل في تداخل بين البروفين والاسبرين",
        "Does ibuprofen interact with my current medications?",
        "اقدر اخذ الاثنين مع بعض؟",
    ],
)
def test_combining_medicines_is_an_interaction_question(question: str) -> None:
    assert classify(question).intent is Intent.INTERACTION


@pytest.mark.parametrize(
    "question",
    [
        "Is this medication safe for someone with heart disease?",
        "Is this medicine safe during pregnancy?",
        "هل البروفين آمن للحامل؟",
        "ينفع مريض القلب ياخد الدوا ده؟",
        "What are the risks of taking Ibuprofen regularly?",
    ],
)
def test_whether_a_medicine_suits_a_condition_is_a_safety_question(question: str) -> None:
    assert classify(question).intent is Intent.DRUG_SAFETY


@pytest.mark.parametrize(
    "question",
    [
        "I have the worst headache of my life, it came suddenly",
        "عندي صداع جالي فجأة وهو أسوأ صداع حسيت بيه",
        "عندي صداع ومعاه تنميل في ايدي الشمال",
        "I have a headache and slurred speech",
        "عندي صداع وزغللة في النظر",
        "I have a fever and a stiff neck with a headache",
        "عندي حرارة ورقبتي متيبسة",
        "وقعت وخبطت راسي ودلوقتي عندي صداع",
        "عندي ألم في الصدر",
        "ابني عنده صداع شديد ومش قادر يتكلم كويس",
    ],
)
def test_red_flags_reported_by_the_person_need_urgent_care(question: str) -> None:
    triage = classify(question)
    assert triage.intent is Intent.RED_FLAG
    assert triage.red_flags


@pytest.mark.parametrize(
    "question",
    [
        "What is a thunderclap headache?",
        "ايه هي أعراض الجلطة؟",
        "I have a mild headache, what can I take?",
    ],
)
def test_reading_about_a_red_flag_is_not_one(question: str) -> None:
    assert classify(question).intent is not Intent.RED_FLAG


def test_a_follow_up_answer_keeps_the_treatment_request_it_answers() -> None:
    earlier = ("عندي صداع نصفي آخد ايه؟",)
    triage = classify("لا مش حامل ومباخدش أدوية تانية", earlier)
    assert triage.intent is Intent.SYMPTOM_TREATMENT
    assert "headache" in triage.symptoms


def test_a_red_flag_in_a_follow_up_still_wins() -> None:
    earlier = ("عندي صداع نصفي آخد ايه؟",)
    assert classify("ايوه عندي تنميل في ايدي", earlier).intent is Intent.RED_FLAG


@pytest.mark.parametrize(
    ("question", "dialect"),
    [
        ("عندي صداع نصفي، آخد إيه؟", Dialect.EGYPTIAN),
        ("ايه الفرق بين الدوا ده والتاني؟", Dialect.EGYPTIAN),
        ("عايز اعرف استخدام البنادول", Dialect.EGYPTIAN),
        ("وش استخدام البنادول؟", Dialect.SAUDI),
        ("ابغى اعرف عن البنادول الحين", Dialect.SAUDI),
        ("ما هي استخدامات الباراسيتامول؟", Dialect.SAUDI),
        ("What is Panadol used for?", Dialect.ENGLISH),
    ],
)
def test_the_answer_dialect_follows_the_question(question: str, dialect: Dialect) -> None:
    assert classify(question).dialect is dialect


def test_every_intent_but_red_flags_gives_the_model_guidance() -> None:
    assert "do not ask" in classify("What is Panadol used for?").guidance.lower()
    treatment = classify("I have a migraine. What medicine could help?").guidance
    assert "pregnan" in treatment
    assert "other medicines" in treatment
    assert "check_interactions" in classify("Can I take Panadol with Sumatriptan?").guidance
    assert "contraindications" in classify("Is this safe in heart disease?").guidance
    assert "Egyptian" in classify("عندي صداع آخد ايه").guidance
