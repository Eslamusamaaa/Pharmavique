"""Linking rows of the official SFDA lists to catalog products. Unsure always means "possible"."""

from pharmavique.catalog.domain.list_linking import LinkableProduct, ProductLinkIndex


def product(
    number: str,
    brand_name: str,
    ingredients: tuple[str, ...],
    companies: tuple[str, ...] = (),
) -> LinkableProduct:
    return LinkableProduct.build(number, brand_name, ingredients, companies)


INDEX = ProductLinkIndex(
    [
        product("1", "TOPAMAX 25 MG TABLET", ("TOPIRAMATE",), ("Janssen Cilag - Belgium",)),
        product("2", "TOPIRAL 50 MG", ("TOPIRAMATE",)),
        product("3", "TOPAMAX 15 MG", ("TOPIRAMATE", "SOMETHING ELSE")),
        product("4", "ZOLADEX", ("GOSERELIN ACETATE",)),
        product("5", "SALINE", ("SODIUM CHLORIDE",)),
    ]
)


def link(list_name: str, **cells: str) -> dict[str, str]:
    result = INDEX.link(list_name, {label.replace("_", " "): v for label, v in cells.items()})
    return {item.register_number: item.confidence for item in result}


def test_brand_and_same_ingredient_is_a_match() -> None:
    assert link("safety-labeling", Trade_Name="Topamax", Scientific_Name="Topiramate") == {
        "1": "matched",
        "3": "possible",  # same brand, but a different ingredient set
    }


def test_brand_alone_is_only_possible() -> None:
    assert link("drug-approvals", Trade_Name="Zoladex", Scientific_Name="Leuprorelin") == {
        "4": "possible"
    }


def test_a_row_with_an_unknown_brand_links_to_nothing_even_if_the_ingredient_is_known() -> None:
    assert link("safety-labeling", Trade_Name="Nothing", Scientific_Name="Topiramate") == {}


def test_a_salt_in_the_registry_still_matches_the_plain_ingredient_name() -> None:
    assert link("drug-approvals", Trade_Name="Zoladex", Scientific_Name="Goserelin") == {
        "4": "matched"
    }


def test_shortage_rows_have_a_generic_name_only_so_every_link_is_possible() -> None:
    assert link("drug-shortage", Generic_Name="TOPIRAMATE") == {"1": "possible", "2": "possible"}
    assert link("drug-shortage", Generic_Name="Sodium chloride") == {"5": "possible"}


def test_a_safety_alert_title_that_names_an_ingredient_is_possible() -> None:
    assert link("safety-alert", Title="Safety Signal of Goserelin and the Risk of X") == {
        "4": "possible"
    }
    assert link("safety-alert", Title="Annual report of 2026") == {}


def test_a_company_row_matches_products_of_that_company_ignoring_the_country_suffix() -> None:
    assert link("drug-companies", Company_Name="JANSSEN CILAG - BELGIUM") == {"1": "matched"}
    assert link("drug-companies", Company_Name="Unknown Co - Egypt") == {}


def test_lists_without_drug_data_link_to_nothing() -> None:
    assert link("pharmacies", Pharmacy_Name="Topamax Pharmacy") == {}


COMPANY_INDEX = ProductLinkIndex(
    [
        product("10", "A", ("X",), ("Granules India Limited Unit V",)),
        product("11", "B", ("Y",), ("Abbott Laboratories",)),
        product("12", "C", ("Z",), ("KVP Pharma + Veterinär Produkte GmbH",)),
        product("13", "D", ("W",), ("Hikma Pharmaceuticals PLC",)),
    ]
)


def company_link(name: str) -> dict[str, str]:
    result = COMPANY_INDEX.link("drug-companies", {"Company Name": name})
    return {item.register_number: item.confidence for item in result}


def test_a_company_that_differs_only_by_legal_form_or_site_is_possible_not_matched() -> None:
    assert company_link("GRANULES INDIA LIMITED - INDIA") == {"10": "possible"}
    assert company_link("ABBOTT LABORATORIES S.A - SPAIN") == {"11": "possible"}
    assert company_link("Hikma Pharmaceuticals PLC - Jordan") == {"13": "matched"}


def test_company_cores_do_not_link_different_companies() -> None:
    assert company_link("AMNEAL PHARMACEUTICALS LLC - USA") == {}
    assert company_link("FLEET LABORATORIES LIMITED - UK") == {}


SHORTAGE_INDEX = ProductLinkIndex(
    [
        product("20", "HYRIMOZ 40 MG", ("ADALIMUMAB",)),
        product("21", "HUMIRA", ("ADALIMUMAB",)),
        product("22", "HYRIMOZ", ("OTHER",)),
    ]
)


def test_a_shortage_row_with_trade_names_matches_only_the_named_brands() -> None:
    found = SHORTAGE_INDEX.link(
        "drug-shortage",
        {"Generic Name": "ADALIMUMAB"},
        (("Trade name", "Hyrimoz"), ("Trade name", "Abrilada")),
    )
    assert {link.register_number: link.confidence for link in found} == {
        "20": "matched",
        "21": "possible",
    }


def test_a_shortage_row_without_trade_names_stays_possible() -> None:
    found = SHORTAGE_INDEX.link("drug-shortage", {"Generic Name": "ADALIMUMAB"})
    assert {link.confidence for link in found} == {"possible"}
