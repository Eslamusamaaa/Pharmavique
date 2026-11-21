"""Listing the conditions a product's ingredients are contraindicated with, from a source."""

from collections.abc import Collection

from pharmavique.interactions.application.contraindications import ListContraindications
from pharmavique.interactions.contracts.queries import ProductIngredients
from pharmavique.interactions.domain.records import ContraindicationRecord


class FakeStore:
    def __init__(self, *records: ContraindicationRecord) -> None:
        self.records = records

    async def for_ingredients(self, keys: Collection[str]) -> list[ContraindicationRecord]:
        wanted = set(keys)
        return [r for r in self.records if r.ingredient in wanted]


def record(ingredient: str, disease: str) -> ContraindicationRecord:
    return ContraindicationRecord(ingredient, disease, "MONDO:1", f"{disease} text.", "medic")


async def test_an_ingredient_with_a_salt_name_finds_its_base_records() -> None:
    report = await ListContraindications(FakeStore(record("metformin", "renal failure"))).run(
        [ProductIngredients("1", "Glucophage", ("METFORMIN HYDROCHLORIDE",))]
    )

    assert [(i.register_number, i.ingredient, i.disease, i.source) for i in report.items] == [
        ("1", "METFORMIN HYDROCHLORIDE", "renal failure", "medic")
    ]
    assert report.items[0].text == "renal failure text."


async def test_several_products_each_get_their_own_items_sorted_by_disease() -> None:
    store = FakeStore(
        record("warfarin", "pregnancy"),
        record("warfarin", "hemorrhage"),
        record("aspirin", "asthma"),
    )

    report = await ListContraindications(store).run(
        [
            ProductIngredients("1", "Coumadin", ("WARFARIN SODIUM",)),
            ProductIngredients("2", "Disprin", ("ACETYLSALICYLIC ACID", "ASPIRIN")),
        ]
    )

    assert [(i.register_number, i.disease) for i in report.items] == [
        ("1", "hemorrhage"),
        ("1", "pregnancy"),
        ("2", "asthma"),
    ]


async def test_nothing_recorded_is_not_a_clearance() -> None:
    report = await ListContraindications(FakeStore()).run(
        [ProductIngredients("1", "Unknown", ("ZZZ",))]
    )

    assert report.items == ()
    assert report.complete is False
