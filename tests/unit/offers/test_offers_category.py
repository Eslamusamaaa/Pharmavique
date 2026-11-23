from pharmavique.offers.domain.category import classify, extract_pack_text
from pharmavique.offers.domain.model import ListingCategory as C


def test_an_empty_category_path_is_unclassified_never_a_medicine() -> None:
    assert classify(()) is C.UNCLASSIFIED
    assert classify(("Home",)) is C.UNCLASSIFIED


def test_medicine_words_in_the_path_make_a_medicine() -> None:
    assert classify(("Home", "Medicines", "Pain Relief")) is C.MEDICINE
    assert classify(("الرئيسية", "الأدوية", "مسكنات")) is C.MEDICINE


def test_the_product_name_alone_never_makes_a_medicine() -> None:
    assert classify(("Home", "Hair Care"), "Panadol tablets") is C.COSMETIC


def test_cosmetics_and_devices_are_told_apart() -> None:
    assert classify(("Home", "Makeup", "Face", "Powder")) is C.COSMETIC
    assert classify(("Home", "Skin Care")) is C.COSMETIC
    assert classify(("Home", "Medical Devices", "Blood Pressure Monitors")) is C.DEVICE
    assert classify(("الرئيسية", "أجهزة طبية")) is C.DEVICE


def test_vitamins_and_baby_food_are_other_even_under_medicines() -> None:
    assert classify(("Home", "Medicines", "Vitamins & Supplements")) is C.OTHER
    assert classify(("Home", "Baby", "Baby Milk")) is C.OTHER


def test_a_cosmetic_inside_a_medicine_branch_is_not_a_medicine() -> None:
    assert classify(("Medicines", "Dermatology", "Skin Care")) is C.COSMETIC


def test_a_category_the_rules_do_not_know_stays_unclassified() -> None:
    assert classify(("Home", "Gifts", "Seasonal")) is C.UNCLASSIFIED


def test_the_pack_size_is_read_from_the_name() -> None:
    assert extract_pack_text("Panadol 500 mg 24 Tablets") == "24 tablets"
    assert extract_pack_text("سبازموليت 20 مجم 30 قرص") == "30 قرص"
    assert extract_pack_text("Syrup 120 ml") == "120 ml"
    assert extract_pack_text("Panadol") is None


def test_a_medicine_word_must_be_a_whole_word() -> None:
    assert classify(("Oral Care", "Fluoride Toothpaste")) is C.UNCLASSIFIED
    assert classify(("Medicines", "Cold & Flu")) is C.MEDICINE
    assert classify(("Cough", "Syrups")) is C.MEDICINE
