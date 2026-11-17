"""What gets indexed for a product, in its normalized form."""

from pharmavique.search.domain.documents import ProductKey, ProductToIndex, build_document
from pharmavique.shared_kernel.market import Market


def product(**overrides: object) -> ProductToIndex:
    fields: dict[str, object] = {
        "key": ProductKey(Market.SA, "1-111-22"),
        "trade_name_en": "PANADOL Extra",
        "trade_name_ar": "بَنادول إكسترا",
        "ingredient_names": ("PARACETAMOL", "CAFFEINE"),
        "marketing_company": "GSK",
        "withdrawn": False,
    }
    fields.update(overrides)
    return ProductToIndex(**fields)  # type: ignore[arg-type]


def test_names_ingredients_and_company_are_normalized_for_matching() -> None:
    document = build_document(product())

    assert document.names == ("panadol extra", "بنادول اكسترا")
    assert document.ingredients == "paracetamol caffeine"
    assert document.company == "gsk"
    assert not document.withdrawn


def test_a_missing_name_is_left_out_rather_than_indexed_as_blank() -> None:
    assert build_document(product(trade_name_ar=None)).names == ("panadol extra",)
    assert build_document(product(trade_name_en=None, trade_name_ar=None)).names == ()


def test_the_register_number_is_kept_verbatim_for_exact_lookups() -> None:
    assert build_document(product()).key.register_number == "1-111-22"
