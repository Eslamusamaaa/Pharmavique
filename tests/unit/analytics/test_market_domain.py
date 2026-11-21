"""The market map and the gap finder, from registry rows only."""

from decimal import Decimal

from pharmavique.analytics.domain.market import (
    IngredientLine,
    MarketProduct,
    build_market_map,
    find_gaps,
)


def product(
    number: str,
    names: tuple[tuple[str, str | None], ...] = (("Paracetamol", "500"),),
    form: str | None = "TABLET",
    company: str | None = "Acme",
    status: str = "listed",
    price: str | None = None,
    code: str | None = "SAR",
    basis: str | None = "source_stated",
) -> MarketProduct:
    return MarketProduct(
        market="SA",
        register_number=number,
        trade_name_en=f"Drug {number}",
        trade_name_ar=None,
        ingredients=tuple(IngredientLine(n, s, "MG" if s else None) for n, s in names),
        dosage_form=form,
        marketing_company=company,
        listing_status=status,
        price_amount=Decimal(price) if price is not None else None,
        price_currency_code=code if price is not None else None,
        price_currency_basis=basis if price is not None else None,
    )


def test_the_market_map_counts_listed_and_withdrawn_separately() -> None:
    rows = [
        product("1"),
        product("2", company="Beta"),
        product("3", status="withdrawn"),
        product("4", names=(("Ibuprofen", "200"),)),
    ]
    result = build_market_map("paracetamol", rows)
    assert (result.listed, result.withdrawn, result.makers) == (2, 1, 2)
    assert result.ingredient == "PARACETAMOL"


def test_a_combination_is_its_own_group() -> None:
    rows = [
        product("1"),
        product("2", names=(("Paracetamol", "500"), ("Caffeine", "65"))),
    ]
    groups = build_market_map("Paracetamol", rows).groups
    assert sorted(g.ingredients for g in groups) == [("CAFFEINE", "PARACETAMOL"), ("PARACETAMOL",)]


def test_price_ranges_never_mix_currencies_or_bases() -> None:
    rows = [
        product("1", price="10"),
        product("2", price="30"),
        product("3", price="5", code="EGP"),
        product("4", price="7", basis="unconfirmed"),
        product("5", status="withdrawn", price="99"),
    ]
    ranges = build_market_map("Paracetamol", rows).groups[0].price_ranges
    keys = {(r.currency_code, r.currency_basis): (r.count, r.lowest, r.highest) for r in ranges}
    assert keys == {
        ("SAR", "source_stated"): (2, Decimal(10), Decimal(30)),
        ("EGP", "source_stated"): (1, Decimal(5), Decimal(5)),
        ("SAR", "unconfirmed"): (1, Decimal(7), Decimal(7)),
    }


def test_a_missing_strength_is_kept_as_not_stated() -> None:
    result = build_market_map("Paracetamol", [product("1", names=(("Paracetamol", None),))])
    assert result.groups[0].strengths == (("PARACETAMOL not stated", 1),)


def test_unknown_ingredient_gives_an_empty_map() -> None:
    result = build_market_map("Nothing", [product("1")])
    assert (result.listed, result.groups) == (0, ())


def test_gaps_call_a_cell_thin_when_few_makers_sell_it() -> None:
    rows = [
        product("1", names=(("Paracetamol", "500"),), company="A"),
        product("2", names=(("Paracetamol", "500"),), company="B"),
        product("3", names=(("Paracetamol", "500"),), company="C"),
        product("4", names=(("Paracetamol", "1000"),), company="A"),
    ]
    gaps = find_gaps("Paracetamol", rows, thin_at=2)
    by_strength = {c.strength_key: c for c in gaps.cells}
    assert by_strength["PARACETAMOL 500 MG"].thin is False
    assert by_strength["PARACETAMOL 1000 MG"].thin is True
    assert gaps.cells[0].strength_key == "PARACETAMOL 1000 MG"  # fewest makers first


def test_missing_cells_pair_strengths_and_forms_that_never_meet() -> None:
    rows = [
        product("1", names=(("Paracetamol", "500"),), form="TABLET"),
        product("2", names=(("Paracetamol", "120"),), form="SYRUP"),
    ]
    missing = {(m.strength_key, m.dosage_form) for m in find_gaps("Paracetamol", rows).missing}
    assert missing == {("PARACETAMOL 500 MG", "SYRUP"), ("PARACETAMOL 120 MG", "TABLET")}


def test_withdrawn_products_do_not_count_as_sold() -> None:
    gaps = find_gaps("Paracetamol", [product("1", status="withdrawn")])
    assert gaps.cells == ()


def test_makers_without_a_company_are_not_counted_as_a_maker() -> None:
    rows = [product("1", company=None), product("2", company=None)]
    assert build_market_map("Paracetamol", rows).makers == 0
    assert find_gaps("Paracetamol", rows).cells[0].makers == 0
