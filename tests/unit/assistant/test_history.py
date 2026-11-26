"""Saved conversations: the rules of docs/PHASE_1_DECISIONS.md, on the in-memory store."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from pharmavique.assistant.application.history import ConversationService, PendingQuestion
from pharmavique.assistant.domain.answers import Level
from pharmavique.assistant.domain.history import (
    MAX_CONVERSATIONS,
    MAX_PINNED,
    MAX_QUESTIONS,
    ConversationFull,
    ConversationNotFound,
    MessageStatus,
    TitleSource,
    TooManyPinned,
    clean_title,
    level_for_roles,
    title_from_question,
)
from pharmavique.assistant.infrastructure.memory_history import MemoryConversationStore
from pharmavique.shared_kernel.errors import InvariantViolation

ME, SOMEONE_ELSE = uuid4(), uuid4()


class TickingClock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        self.at += timedelta(seconds=1)
        return self.at


def service() -> tuple[ConversationService, MemoryConversationStore]:
    store = MemoryConversationStore()
    return ConversationService(store, TickingClock()), store


async def ask(
    svc: ConversationService,
    question: str,
    conversation_id: UUID | None = None,
    answer: str = "جواب",
) -> PendingQuestion:
    pending = await svc.begin(ME, conversation_id, Level.PATIENT, question)
    await svc.answered(ME, pending, answer, {"citations": []})
    return pending


async def test_a_first_question_starts_a_conversation_titled_from_the_question() -> None:
    svc, _ = service()

    pending = await ask(svc, "وش الفرق بين بنادول وبنادول اكسترا؟")

    assert pending.created
    conversation, messages = await svc.open(ME, pending.conversation.id)
    assert conversation.title == "وش الفرق بين بنادول وبنادول اكسترا؟"
    assert conversation.title_source is TitleSource.QUESTION
    assert [(m.role.value, m.text, m.status) for m in messages] == [
        ("user", "وش الفرق بين بنادول وبنادول اكسترا؟", MessageStatus.OK),
        ("assistant", "جواب", MessageStatus.OK),
    ]
    assert messages[1].payload == {"citations": []}


async def test_a_follow_up_gets_the_earlier_turns_from_storage() -> None:
    svc, _ = service()
    first = await ask(svc, "بنادول 500؟", answer="قرص باراسيتامول")

    follow = await svc.begin(ME, first.conversation.id, Level.PATIENT, "وال 1000؟")

    assert not follow.created
    assert [(t.role, t.text) for t in follow.history] == [
        ("user", "بنادول 500؟"),
        ("assistant", "قرص باراسيتامول"),
    ]


async def test_a_failed_answer_keeps_the_question_and_asking_again_replaces_it() -> None:
    svc, _ = service()
    first = await ask(svc, "سؤال أول")
    pending = await svc.begin(ME, first.conversation.id, Level.PATIENT, "سؤال ثاني")
    await svc.failed(ME, pending)

    _, messages = await svc.open(ME, first.conversation.id)
    assert messages[-1].status is MessageStatus.FAILED

    again = await svc.begin(ME, first.conversation.id, Level.PATIENT, "سؤال  ثاني")
    await svc.answered(ME, again, "جواب ثاني", {})

    conversation, messages = await svc.open(ME, first.conversation.id)
    assert again.question_id == pending.question_id
    assert [m.text for m in messages] == ["سؤال أول", "جواب", "سؤال ثاني", "جواب ثاني"]
    assert conversation.questions == 2
    assert ("user", "سؤال ثاني") not in [(t.role, t.text) for t in again.history]


async def test_the_oldest_unpinned_conversation_makes_room_at_the_cap() -> None:
    svc, _ = service()
    first = await ask(svc, "الأقدم")
    await svc.pin(ME, first.conversation.id, True)
    second = await ask(svc, "الأقدم غير المثبت")
    for i in range(MAX_CONVERSATIONS - 2):
        await ask(svc, f"سؤال {i}")

    await ask(svc, "الجديد")

    found, total = await svc.conversations(ME, Level.PATIENT)
    assert total == MAX_CONVERSATIONS
    ids = [c.id for c in found]
    assert first.conversation.id in ids  # pinned: never deleted to make room
    assert second.conversation.id not in ids
    assert found[0].id == first.conversation.id  # pinned first
    assert found[1].title == "الجديد"  # then the most recent


async def test_at_most_ten_pinned() -> None:
    svc, _ = service()
    ids = [(await ask(svc, f"سؤال {i}")).conversation.id for i in range(MAX_PINNED + 1)]
    for conversation_id in ids[:MAX_PINNED]:
        await svc.pin(ME, conversation_id, True)

    with pytest.raises(TooManyPinned):
        await svc.pin(ME, ids[-1], True)
    await svc.pin(ME, ids[0], False)
    assert (await svc.pin(ME, ids[-1], True)).pinned


async def test_a_conversation_holds_at_most_a_hundred_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, store = service()
    first = await ask(svc, "سؤال")
    row = store._rows[first.conversation.id]
    from dataclasses import replace

    row.conversation = replace(row.conversation, questions=MAX_QUESTIONS)

    with pytest.raises(ConversationFull):
        await svc.begin(ME, first.conversation.id, Level.PATIENT, "سؤال جديد")


async def test_lists_are_per_level_and_per_person() -> None:
    svc, _ = service()
    await ask(svc, "سؤال مريض")
    await svc.begin(ME, None, Level.PHARMACIST, "سؤال صيدلي")
    await svc.begin(SOMEONE_ELSE, None, Level.PATIENT, "سؤال غيري")

    patient, _ = await svc.conversations(ME, Level.PATIENT)
    pharmacist, _ = await svc.conversations(ME, Level.PHARMACIST)

    assert [c.title for c in patient] == ["سؤال مريض"]
    assert [c.title for c in pharmacist] == ["سؤال صيدلي"]


async def test_someone_else_cannot_open_rename_or_delete_my_conversation() -> None:
    svc, _ = service()
    mine = await ask(svc, "سؤالي")

    for action in (
        svc.open(SOMEONE_ELSE, mine.conversation.id),
        svc.rename(SOMEONE_ELSE, mine.conversation.id, "عنوان"),
        svc.delete(SOMEONE_ELSE, mine.conversation.id),
        svc.share(SOMEONE_ELSE, mine.conversation.id),
        svc.begin(SOMEONE_ELSE, mine.conversation.id, Level.PATIENT, "سؤال"),
    ):
        with pytest.raises(ConversationNotFound):
            await action


async def test_search_matches_titles_questions_and_answers_after_normalization() -> None:
    svc, _ = service()
    await ask(svc, "سؤال عن الأسبرين", answer="جرعة")
    await ask(svc, "سؤال ثاني", answer="الباراسيتامول مسكن")
    await ask(svc, "شي ثالث")

    by_question, _ = await svc.conversations(ME, Level.PATIENT, "اسبرين")  # alef without hamza
    by_answer, _ = await svc.conversations(ME, Level.PATIENT, "باراسيتامول")

    assert [c.title for c in by_question] == ["سؤال عن الأسبرين"]
    assert [c.title for c in by_answer] == ["سؤال ثاني"]


async def test_the_model_title_replaces_only_the_question_title() -> None:
    svc, _ = service()
    pending = await ask(svc, "سؤال طويل عن دواء")

    titled = await svc.model_title(ME, pending.conversation.id, '"مقارنة بنادول"')
    assert (titled.title, titled.title_source) == ("مقارنة بنادول", TitleSource.MODEL)

    renamed = await svc.rename(ME, pending.conversation.id, "  اسمي أنا ")
    assert (renamed.title, renamed.title_source) == ("اسمي أنا", TitleSource.PERSON)
    kept = await svc.model_title(ME, pending.conversation.id, "عنوان آخر")
    assert kept.title == "اسمي أنا"


async def test_a_failed_model_title_keeps_the_question_title() -> None:
    svc, _ = service()
    pending = await ask(svc, "سؤال")

    assert (await svc.model_title(ME, pending.conversation.id, None)).title == "سؤال"
    assert (await svc.model_title(ME, pending.conversation.id, "  ")).title == "سؤال"


async def test_a_share_link_shows_the_conversation_as_it_was_and_dies_with_it() -> None:
    svc, _ = service()
    pending = await ask(svc, "سؤال", answer="جواب")
    token = await svc.share(ME, pending.conversation.id)
    await ask(svc, "سؤال بعد المشاركة", conversation_id=pending.conversation.id)

    copy = await svc.shared(token)
    assert [m.text for m in copy.messages] == ["سؤال", "جواب"]
    assert await svc.share(ME, pending.conversation.id) == token  # sharing again: same link
    assert len((await svc.shared(token)).messages) == 4

    await svc.delete(ME, pending.conversation.id)
    with pytest.raises(ConversationNotFound):
        await svc.shared(token)


async def test_a_revoked_link_no_longer_opens() -> None:
    svc, _ = service()
    pending = await ask(svc, "سؤال")
    token = await svc.share(ME, pending.conversation.id)

    await svc.unshare(ME, pending.conversation.id)

    with pytest.raises(ConversationNotFound):
        await svc.shared(token)


async def test_delete_all_and_forget() -> None:
    svc, _ = service()
    await ask(svc, "واحد")
    await ask(svc, "اثنين")
    await svc.begin(ME, None, Level.PHARMACIST, "صيدلي")

    assert await svc.delete_all(ME, Level.PATIENT) == 2
    assert (await svc.conversations(ME, Level.PHARMACIST))[1] == 1
    await svc.forget(ME)
    assert (await svc.conversations(ME, Level.PHARMACIST))[1] == 0


def test_the_level_comes_from_the_account_role() -> None:
    assert level_for_roles(frozenset({"patient"}), Level.CLINICAL) is Level.PATIENT
    assert level_for_roles(frozenset({"pharmacist"}), Level.PATIENT) is Level.PHARMACIST
    assert level_for_roles(frozenset({"company"}), Level.PATIENT) is Level.CLINICAL
    assert level_for_roles(frozenset({"operator"}), Level.PHARMACIST) is Level.PHARMACIST


def test_titles() -> None:
    assert title_from_question("  قصير  ") == "قصير"
    assert title_from_question("ب" * 60) == "ب" * 40 + "…"
    assert clean_title("«عنوان»\n") == "عنوان"
    with pytest.raises(InvariantViolation):
        clean_title(' "" ')


def test_search_wildcards_are_escaped_for_like() -> None:
    from pharmavique.assistant.infrastructure.postgres_history import _like

    assert _like("50%_a\\") == "%50\\%\\_a\\\\%"
