"""Listing the conditions a product's ingredients are contraindicated with, from a source."""

from collections.abc import Collection

import pytest

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


async def test_a_disease_the_label_text_does_not_contain_is_not_shown() -> None:
    wrong = ContraindicationRecord(
        "bicarbonate ion",
        "peptic ulcer",
        "MONDO:2",
        "Potassium supplements and hyperkalemia.",
        "medic",
    )
    right = record("metformin", "renal failure")

    report = await ListContraindications(FakeStore(wrong, right)).run(
        [
            ProductIngredients("1", "A", ("BICARBONATE ION",)),
            ProductIngredients("2", "B", ("METFORMIN",)),
        ]
    )

    assert [(i.register_number, i.disease) for i in report.items] == [("2", "renal failure")]
    assert report.hidden_unverified == 1


async def test_the_disease_is_found_in_the_text_whatever_the_case_or_spacing() -> None:
    spaced = ContraindicationRecord(
        "x", "renal failure", "", "Not for patients with Renal   Failure.", "medic"
    )

    report = await ListContraindications(FakeStore(spaced)).run(
        [ProductIngredients("1", "A", ("X",))]
    )

    assert len(report.items) == 1
    assert report.hidden_unverified == 0


def labelled(ingredient: str, disease: str, text: str) -> ContraindicationRecord:
    return ContraindicationRecord(ingredient, disease, "", text, "medic")


async def shown(*records: ContraindicationRecord) -> list[str]:
    ingredient = records[0].ingredient.upper()
    report = await ListContraindications(FakeStore(*records)).run(
        [ProductIngredients("1", "A", (ingredient,))]
    )
    return [i.disease for i in report.items]


# Real MeDIC label texts (shortened) behind rows that named a condition the drug is NOT
# contraindicated with.
STATIN = (
    "Atorvastatin is contraindicated in: Acute liver failure or decompensated cirrhosis. "
    "Lipid lowering drugs during pregnancy should have little impact on the outcome of long-term "
    "therapy of primary hypercholesterolemia. Atherosclerosis is a chronic process."
)


async def test_a_condition_named_only_outside_the_contraindicated_sentences_is_not_shown() -> None:
    found = await shown(
        labelled("atorvastatin", "acute liver failure", STATIN),
        labelled("atorvastatin", "primary hypercholesterolemia", STATIN),
        labelled("atorvastatin", "atherosclerosis", STATIN),
    )

    assert found == ["acute liver failure"]


async def test_a_reaction_described_after_the_hypersensitivity_sentence_is_not_shown() -> None:
    text = (
        "Pantoprazole is contraindicated in patients with known hypersensitivity to any component. "
        "Hypersensitivity reactions may include anaphylaxis, angioedema, bronchospasm."
    )

    assert await shown(labelled("pantoprazole", "bronchospasm", text)) == []


async def test_a_label_that_is_only_a_list_of_conditions_is_shown() -> None:
    assert await shown(labelled("hydrochlorothiazide", "anuria", "Anuria. Hypersensitivity.")) == [
        "anuria"
    ]


async def test_a_general_condition_inside_a_more_specific_one_is_not_shown_on_its_own() -> None:
    text = (
        "Patients with status asthmaticus or other acute episodes of asthma where intensive "
        "measures are required."
    )

    found = await shown(
        labelled("mometasone", "asthma", text), labelled("mometasone", "status asthmaticus", text)
    )

    assert found == ["status asthmaticus"]


async def test_a_condition_that_applies_to_one_route_or_population_only_is_not_shown() -> None:
    preterm = (
        "Ibuprofen lysine is contraindicated in: Preterm infants with congenital heart disease in "
        "whom patency of the PDA is necessary."
    )
    eye = (
        "Contraindicated in most viral diseases of the cornea and conjunctiva including "
        "vaccinia, and in fungal diseases of ocular structures."
    )

    assert await shown(labelled("ibuprofen", "congenital heart disease", preterm)) == []
    assert await shown(labelled("dexamethasone", "vaccinia", eye)) == []


async def test_a_condition_that_only_applies_with_another_drug_or_in_pregnancy_is_not_shown() -> (
    None
):
    combined = (
        "Concomitant administration of clarithromycin and colchicine is contraindicated in "
        "patients with renal or hepatic impairment."
    )
    pregnant = "Methotrexate is contraindicated in pregnant women with psoriasis or arthritis."

    assert await shown(labelled("clarithromycin", "hepatic impairment", combined)) == []
    assert await shown(labelled("methotrexate", "psoriasis", pregnant)) == []


async def test_a_label_written_for_an_eye_or_inhaled_product_is_not_shown_for_the_ingredient() -> (
    None
):
    implant = (
        "Ocular or periocular infections ( 4.1 ) Glaucoma ( 4.2 ) Torn or ruptured posterior lens "
        "capsule ( 4.3 ). OZURDEX is an intravitreal implant."
    )

    assert await shown(labelled("dexamethasone", "glaucoma", implant)) == []


async def test_a_general_condition_is_hidden_when_another_label_of_the_ingredient_is_specific() -> (
    None
):
    one = "Primary treatment of status asthmaticus or other acute episodes of asthma."
    other = "PULMICORT is contraindicated in the primary treatment of status asthmaticus."

    found = await shown(
        labelled("budesonide", "asthma", one), labelled("budesonide", "status asthmaticus", other)
    )

    assert found == ["status asthmaticus"]


async def test_a_sentence_about_what_the_drug_treats_is_not_a_contraindication() -> None:
    text = (
        "Post-irradiation proctitis; as an adjunct in the treatment of chronic ulcerative colitis."
    )

    assert await shown(labelled("hydrocortisone", "chronic ulcerative colitis", text)) == []


async def test_a_route_word_far_down_a_systemic_label_does_not_hide_the_label() -> None:
    text = (
        "Warfarin is contraindicated in: Pregnancy. Hemorrhagic tendencies or blood dyscrasias. "
        + "Other situations. " * 12
        + "Spinal puncture and other diagnostic or therapeutic procedures with potential for "
        "uncontrollable bleeding."
    )

    assert await shown(labelled("warfarin", "hemorrhagic tendencies", text)) == [
        "hemorrhagic tendencies"
    ]


async def test_a_list_item_of_a_text_that_says_what_the_drug_treats_is_not_shown() -> None:
    text = (
        "Hydrocortisone is contraindicated in patients with hypersensitivity. Indicated for "
        "proctitis; as an adjunct in the treatment of chronic ulcerative colitis; cryptitis; and "
        "other inflammatory conditions."
    )

    assert await shown(labelled("hydrocortisone", "cryptitis", text)) == []


async def test_items_after_dashes_in_a_contraindicated_list_are_shown() -> None:
    text = (
        "Warfarin is contraindicated in: Bleeding tendencies associated with: "
        "\u2013 central nervous system hemorrhage \u2013 pericarditis and pericardial effusions "
        "\u2013 bacterial endocarditis. Other text that is long enough to be a statement here."
    )

    assert await shown(labelled("warfarin", "pericarditis", text)) == ["pericarditis"]


async def test_a_label_text_with_no_contraindicated_word_that_lists_uses_is_not_shown() -> None:
    text = "For wounds or scaly skin (ichthyosis). Relief of itching in eczema."

    assert await shown(labelled("hydrocortisone", "ichthyosis", text)) == []


async def test_a_label_written_for_a_cream_is_not_shown_for_the_ingredient() -> None:
    text = (
        "Do not use Aquax-H Cream if your skin condition is caused by infections. "
        "For wounds or scaly skin (ichthyosis)."
    )

    assert await shown(labelled("hydrocortisone", "ichthyosis", text)) == []


@pytest.mark.parametrize(
    ("ingredient", "disease", "text"),
    [
        # real label sentences where the condition is only a qualifier of something else
        ("glimepiride", "coma", "Glimepiride is contraindicated in: Diabetic ketoacidosis, with or "
         "without coma."),
        ("epinephrine", "shock", "Epinephrine is contraindicated in patients with angle closure "
         "glaucoma, and patients in shock (nonanaphylactic)."),
        ("morphine", "diarrhea", "It should not be used in diarrhea caused by poisoning until the "
         "toxic material is eliminated."),
        ("methotrexate", "psoriasis", "Patients with psoriasis or rheumatoid arthritis who have "
         "immunodeficiency syndromes should not receive methotrexate."),
        ("metoprolol", "myocardial infarction", "Metoprolol is contraindicated in sinus "
         "bradycardia. Myocardial Infarction Metoprolol is contraindicated in patients with a "
         "heart rate below 45."),
        ("metformin", "shock", "Metformin is contraindicated in renal dysfunction which may also "
         "result from conditions such as cardiovascular collapse (shock)."),
        ("glycerin", "nephrotic syndrome", "Children with nephrotic syndrome probably should not "
         "receive injections."),
        ("ibuprofen", "asthma", "Ibuprofen should not be given to patients who have experienced "
         "asthma after taking aspirin or other NSAIDs."),
        ("leucovorin", "megaloblastic anemia", "Leucovorin is contraindicated as therapy for "
         "megaloblastic anemias secondary to the lack of vitamin B12."),
        ("pilocarpine", "glaucoma", "Pilocarpine is contraindicated when miosis is undesirable, "
         "e.g., in acute iritis and pupillary block glaucoma."),
    ],
)  # fmt: skip
async def test_a_condition_named_only_as_a_qualifier_or_with_a_hedge_is_not_shown(
    ingredient: str, disease: str, text: str
) -> None:
    assert await shown(labelled(ingredient, disease, text)) == []


async def test_a_pregnancy_contraindication_itself_is_still_shown() -> None:
    text = "ARAVA is contraindicated in: Pregnant women."

    assert await shown(labelled("leflunomide", "pregnant", text)) == ["pregnant"]


async def test_nothing_from_a_label_is_shown_for_a_product_used_on_the_skin_or_the_eye() -> None:
    record = labelled(
        "lidocaine",
        "wolff-parkinson-white syndrome",
        "Lidocaine is contraindicated in patients with Wolff-Parkinson-White syndrome.",
    )
    store = FakeStore(record)

    report = await ListContraindications(store).run(
        [
            ProductIngredients("1", "XYLOCAINE GEL", ("LIDOCAINE",), "Cutaneous use", "Gel"),
            ProductIngredients("2", "LIDOCAINE INJ", ("LIDOCAINE",), "Intravenous use", None),
        ]
    )

    assert [i.register_number for i in report.items] == ["2"]
    assert report.hidden_unverified == 1
