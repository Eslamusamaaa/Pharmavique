"""Reading the text on the picture itself: is this really the box of that drug?

The texts below are what the Windows OCR engine returned for real pictures of Saudi shop pages.
"""

from pharmavique.media.domain.matching import ProductRef
from pharmavique.media.domain.verification import PictureVerdict, verify_picture
from pharmavique.shared_kernel.market import Market


def product(
    name: str = "PANADOL EXTRA TAB",
    ingredients: tuple[str, ...] = ("PARACETAMOL", "CAFFEINE CITRATE"),
    strengths: tuple[str, ...] = ("500 mg", "65 mg"),
) -> ProductRef:
    return ProductRef(Market.SA, "1-1", name, None, ingredients, None, strengths)


def test_the_brand_name_on_the_box_confirms_it() -> None:
    result = verify_picture(
        product(), 'Panadol Extra Extra • effedivepcinre/ief Red"es foe,• 24 TABLETS'
    )

    assert result.verdict is PictureVerdict.CONFIRMED
    assert "brand" in result.signals


def test_every_word_of_the_brand_must_be_on_the_box() -> None:
    # "Panadol Advance" is a different product from "Panadol Extra"
    result = verify_picture(product(), "Panadol Advance fast pain relief 24 tablets")

    assert result.verdict is PictureVerdict.NOT_CONFIRMED


def test_ocr_noise_inside_the_brand_is_tolerated() -> None:
    assert (
        verify_picture(
            product("GLUCOPHAGE 500 mg tablet", ("METFORMIN",), ("500 mg",)),
            "500 my VGlucophageØ Tablets / Comprimés Metformin 100 tablets",
        ).verdict
        is PictureVerdict.CONFIRMED
    )
    assert verify_picture(product(), "Panadoi Extra 24 TABLETS").verdict is PictureVerdict.CONFIRMED


def test_a_symbol_glued_to_the_brand_does_not_hide_it() -> None:
    result = verify_picture(
        product("BRUFEN 400 MG TAB", ("IBUPROFEN",), ("400 mg",)),
        "BRUFEN@400 400 mg Ibuprofen B.P • Fast pain relief 30 Tablets",
    )

    assert result.verdict is PictureVerdict.CONFIRMED
    assert "strength" in result.signals


def test_the_same_brand_with_only_a_different_strength_is_a_conflict() -> None:
    result = verify_picture(
        product("GLUCOPHAGE 500 mg tablet", ("METFORMIN",), ("500 mg",)),
        "GLUCOPHAGE XR 750mg Prolonged release tablets Metformin hydrochloride 30 Tablets",
    )

    assert result.verdict is PictureVerdict.STRENGTH_CONFLICT


def test_ingredient_and_strength_without_the_brand_is_only_likely() -> None:
    result = verify_picture(
        product("GLUCOPHAGE 500 mg tablet", ("METFORMIN",), ("500 mg",)),
        "Metformin 500 mg 100 tablets",
    )

    assert result.verdict is PictureVerdict.LIKELY


def test_a_box_whose_text_cannot_be_read_is_not_confirmed_never_guessed() -> None:
    assert verify_picture(product(), "").verdict is PictureVerdict.NOT_CONFIRMED
    assert "no_text" in verify_picture(product(), "   ").signals
    assert verify_picture(product(), "24 TABLETS").verdict is PictureVerdict.NOT_CONFIRMED


def test_a_brand_that_is_short_must_match_exactly() -> None:
    # "Imuran" must not be confirmed by "Imaging" or "Murano"
    assert verify_picture(product("IMURAN", (), ()), "Imaging solutions Murano glass").verdict is (
        PictureVerdict.NOT_CONFIRMED
    )
    assert verify_picture(product("IMURAN", (), ()), "Imuran 50 mg Azathioprine").verdict is (
        PictureVerdict.CONFIRMED
    )


def test_a_name_made_only_of_form_words_cannot_confirm_anything() -> None:
    result = verify_picture(product("Tablet", (), ()), "Tablet 24 tablets")

    assert result.verdict is PictureVerdict.NOT_CONFIRMED
