"""Finding the drug name in a spoken request: model first, rules as the fallback."""

import pytest

from pharmavique.voice.application.extract import ExtractDrugName
from pharmavique.voice.domain.names import clean_model_name, strip_filler


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("أنا عايز بنادول", "بنادول"),
        ("انا عايز بروفين", "بروفين"),
        ("عايز اعرف سعر بانادول اكسترا", "بانادول اكسترا"),
        ("ابغى دواء كونكور 10 ملغ", "كونكور 10 ملغ"),
        ("I want Panadol please", "Panadol"),
        ("عايز دوا", "عايز دوا"),  # only filler: the words stay rather than an empty search
    ],
)
def test_request_words_are_removed_and_the_name_stays(spoken: str, expected: str) -> None:
    assert strip_filler(spoken) == expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("بنادول", "بنادول"),
        ('"Panadol Extra"', "Panadol Extra"),
        ("بروفين.\nشرح عن الدواء", "بروفين"),
        ("NONE", None),
        ("", None),
        ("لا يوجد", None),
        ("أنا لم أجد أي دواء مذكور في الجملة التي قلتها لك اليوم يا صديقي العزيز", None),
    ],
)
def test_a_models_reply_becomes_a_name_or_nothing(answer: str, expected: str | None) -> None:
    assert clean_model_name(answer) == expected


class FakeExtractor:
    def __init__(self, reply: str | None = None, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.heard: list[str] = []

    async def extract(self, text: str) -> str | None:
        self.heard.append(text)
        if self.fail:
            raise RuntimeError("rate limited")
        return self.reply


async def test_the_models_name_is_what_gets_searched() -> None:
    extractor = FakeExtractor("بنادول")

    result = await ExtractDrugName(extractor).run("أنا عايز بنادول")

    assert (result.query, result.name, result.understood) == ("بنادول", "بنادول", True)
    assert extractor.heard == ["أنا عايز بنادول"]


async def test_a_failing_model_falls_back_to_the_rules() -> None:
    result = await ExtractDrugName(FakeExtractor(fail=True)).run("أنا عايز بروفين")

    assert (result.query, result.name, result.understood) == ("بروفين", None, False)


async def test_without_a_model_the_rules_still_clean_the_sentence() -> None:
    result = await ExtractDrugName(None).run("انا عايز بنادول")

    assert result.query == "بنادول"


async def test_a_model_that_names_nothing_falls_back_to_the_rules() -> None:
    result = await ExtractDrugName(FakeExtractor("NONE")).run("عايز كونكور")

    assert (result.query, result.understood) == ("كونكور", False)


async def test_empty_or_huge_speech_is_refused() -> None:
    with pytest.raises(ValueError, match="characters"):
        await ExtractDrugName(None).run("   ")
