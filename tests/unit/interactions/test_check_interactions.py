"""Checking a set of products for interactions, duplicates and ingredients we cannot judge."""

from collections.abc import Collection

from pharmavique.interactions.application.check import CheckInteractions, ProductIngredients
from pharmavique.interactions.domain.records import InteractionRecord
from pharmavique.interactions.domain.severity import Severity


class FakeStore:
    def __init__(self, *records: InteractionRecord) -> None:
        self.records = records

    async def known(self, keys: Collection[str]) -> set[str]:
        wanted = set(keys)
        known = {r.ingredient_a for r in self.records} | {r.ingredient_b for r in self.records}
        return known & wanted

    async def pairs_among(self, keys: Collection[str]) -> list[InteractionRecord]:
        wanted = set(keys)
        return [r for r in self.records if {r.ingredient_a, r.ingredient_b} <= wanted]


WARFARIN_ASPIRIN = InteractionRecord("aspirin", "warfarin", Severity.MAJOR, "ddinter-2.0")


def product(register: str, *ingredients: str) -> ProductIngredients:
    return ProductIngredients(register, f"drug {register}", tuple(ingredients))


async def test_a_recorded_pair_across_two_products_is_reported_with_its_source() -> None:
    check = CheckInteractions(FakeStore(WARFARIN_ASPIRIN))

    report = await check.run([product("1", "WARFARIN SODIUM"), product("2", "ASPIRIN")])

    assert [(f.kind, f.severity, f.registers) for f in report.findings] == [
        ("interaction", "major", ("1", "2"))
    ]
    assert report.findings[0].source == "ddinter-2.0"
    assert report.findings[0].ingredients == ("WARFARIN SODIUM", "ASPIRIN")


async def test_two_products_with_the_same_ingredient_are_a_duplicate() -> None:
    report = await CheckInteractions(FakeStore()).run(
        [product("1", "PARACETAMOL"), product("2", "PARACETAMOL")]
    )

    assert [(f.kind, f.severity, f.registers) for f in report.findings] == [
        ("duplicate_ingredient", None, ("1", "2"))
    ]


async def test_salt_and_base_names_count_as_the_same_ingredient_for_duplicates() -> None:
    report = await CheckInteractions(FakeStore()).run(
        [product("1", "METFORMIN HYDROCHLORIDE"), product("2", "METFORMIN")]
    )

    assert [f.kind for f in report.findings] == ["duplicate_ingredient"]


async def test_ingredients_the_source_does_not_know_are_listed_not_called_safe() -> None:
    report = await CheckInteractions(FakeStore(WARFARIN_ASPIRIN)).run(
        [product("1", "WARFARIN"), product("2", "ZZZ-NEW-MOLECULE")]
    )

    assert report.findings == ()
    assert report.unmatched == (("2", "ZZZ-NEW-MOLECULE"),)


async def test_pairs_inside_one_combination_product_are_not_reported() -> None:
    report = await CheckInteractions(FakeStore(WARFARIN_ASPIRIN)).run(
        [product("1", "WARFARIN", "ASPIRIN")]
    )

    assert report.findings == ()


async def test_the_same_pair_is_reported_once_even_if_two_products_repeat_an_ingredient() -> None:
    report = await CheckInteractions(FakeStore(WARFARIN_ASPIRIN)).run(
        [product("1", "WARFARIN"), product("2", "ASPIRIN"), product("3", "ASPIRIN")]
    )

    pairs = sorted(f.registers for f in report.findings if f.kind == "interaction")
    assert pairs == [("1", "2"), ("1", "3")]


async def test_findings_come_most_severe_first_and_the_report_says_it_is_not_a_safety_verdict() -> (
    None
):
    store = FakeStore(
        InteractionRecord("a", "b", Severity.MINOR, "ddinter-2.0"),
        InteractionRecord("a", "c", Severity.MAJOR, "ddinter-2.0"),
    )

    report = await CheckInteractions(store).run(
        [product("1", "A"), product("2", "B"), product("3", "C")]
    )

    assert [f.severity for f in report.findings] == ["major", "minor"]
    assert report.complete is False  # absence of a finding is never "safe"
