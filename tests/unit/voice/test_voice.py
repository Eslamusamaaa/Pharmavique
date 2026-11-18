"""Speech: what is spoken (no citation marks or links), in pieces the provider accepts."""

from collections.abc import Sequence

import pytest

from pharmavique.voice.application.speak import Speak, Transcribe
from pharmavique.voice.domain.speech import MAX_SEGMENT, speakable, split_for_speech


def test_citation_marks_links_and_extra_spaces_are_not_spoken() -> None:
    text = "المادة الفعالة هي الباراسيتامول [1]【2】. المصدر https://www.sfda.gov.sa/x  هنا."

    assert speakable(text) == "المادة الفعالة هي الباراسيتامول. المصدر هنا."


def test_short_text_stays_one_segment() -> None:
    assert split_for_speech("هلا والله.") == ["هلا والله."]


def test_long_text_is_cut_at_sentence_ends_under_the_limit() -> None:
    sentence = "البنادول فيه مادة الباراسيتامول وهي مسكنة للألم وخافضة للحرارة حسب النشرة. "
    segments = split_for_speech(sentence * 6)

    assert len(segments) > 1
    assert all(0 < len(s) <= MAX_SEGMENT for s in segments)
    assert all(s.endswith(".") for s in segments)
    assert " ".join(segments).replace("  ", " ") == (sentence * 6).strip()


def test_a_sentence_longer_than_the_limit_is_cut_between_words() -> None:
    words = ("كلمة " * 120).strip()

    segments = split_for_speech(words)

    assert all(len(s) <= MAX_SEGMENT for s in segments)
    assert " ".join(segments) == words


class FakeTTS:
    max_segment = 200
    media_type = "audio/wav"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def synthesize(self, segments: Sequence[str]) -> bytes:
        self.calls.append(list(segments))
        return b"RIFF-joined"


class FakeSTT:
    async def transcribe(self, audio: bytes, filename: str, language: str) -> str:
        return f"{language}:{len(audio)}"


async def test_speak_sends_clean_segments_and_returns_one_audio() -> None:
    tts = FakeTTS()

    audio = await Speak(tts).run("هلا [1]. البنادول مسكن.")

    assert audio.content == b"RIFF-joined"
    assert audio.media_type == "audio/wav"
    assert tts.calls == [["هلا. البنادول مسكن."]]


async def test_nothing_to_say_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing to say"):
        await Speak(FakeTTS()).run("[1] https://x.y")


async def test_transcribe_defaults_to_arabic_and_refuses_empty_audio() -> None:
    assert await Transcribe(FakeSTT()).run(b"abc", "a.m4a") == "ar:3"
    with pytest.raises(ValueError, match="audio"):
        await Transcribe(FakeSTT()).run(b"", "a.m4a")


async def test_segments_follow_the_provider_limit() -> None:
    class LongTTS(FakeTTS):
        max_segment = 1000

    tts = LongTTS()
    sentence = "البنادول فيه مادة الباراسيتامول وهي مسكنة للألم وخافضة للحرارة حسب النشرة. "

    await Speak(tts).run(sentence * 6)

    assert len(tts.calls[0]) == 1
