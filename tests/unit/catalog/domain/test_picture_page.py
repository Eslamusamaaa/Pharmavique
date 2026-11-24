"""A shop picture is not shown for a product when its page names another variant or strength."""

import pytest

from pharmavique.catalog.domain.picture_page import page_names_another_product


@pytest.mark.parametrize(
    ("page", "names", "strengths"),
    [
        # real mappings: the shop page is another product of the brand
        (
            "https://ibrand.com.sa/ar/%D8%A8%D8%A7%D9%86%D8%A7%D8%AF%D9%88%D9%84-%D8%A7%D9%83%D8%B3%D8%AA%D8%B1%D8%A7-24-%D9%82%D8%B1%D8%B5/p174944527",
            ("PANADOL 500 mg film-coated tablet", "بانادول 500 ملجم"),
            ("500",),
        ),
        ("https://x.sa/quetta-xr-400-mg-30-tablets", ("QUETTA 25 mg film-coated tablet",), ("25",)),
        ("https://x.sa/cephadar-forte-500-mg-20-capsules.html", ("CEPHADAR",), ("250",)),
        ("https://x.sa/omol-extra-20-tablets.html", ("OMOL 500MG TABLET",), ("500",)),
        ("https://x.sa/formit-750-mg-30-tablets", ("FORMIT 850 MG TABLETS",), ("850",)),
    ],
)
def test_a_page_of_another_variant_or_strength_is_another_product(
    page: str, names: tuple[str, ...], strengths: tuple[str, ...]
) -> None:
    assert page_names_another_product(page, names, strengths)


@pytest.mark.parametrize(
    ("page", "names", "strengths"),
    [
        ("https://x.sa/panadol-500-mg-24-tablets", ("PANADOL 500 mg tablet",), ("500",)),
        ("https://x.sa/quetta-xr-400-mg", ("QUETTA XR 400 mg prolonged-release tablet",), ("400",)),
        ("https://x.sa/augmentin-1g-14-tablets", ("AUGMENTIN 1 G TAB",), ("875", "125")),
        ("https://x.sa/p/123456", ("CONCOR",), ("5",)),
        ("https://x.sa/hepavir-fc-05-mg-30-tablet/pdp/1", ("HEPAVIR 0.5 mg tablet",), ("0.5",)),
        ("https://x.sa/irma-h-300-12-5-mg-28", ("IRMA-HCT 300 mg / 12.5 mg",), ("300", "12.5")),
        (None, ("CONCOR",), ("5",)),
    ],
)
def test_a_page_of_the_same_product_is_kept(
    page: str | None, names: tuple[str, ...], strengths: tuple[str, ...]
) -> None:
    assert not page_names_another_product(page, names, strengths)
