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
    # HUMIRA has the ingredient but is not one of the trade names SFDA lists: not linked at all
    assert {link.register_number: link.confidence for link in found} == {"20": "matched"}


def test_a_shortage_row_without_trade_names_stays_possible() -> None:
    found = SHORTAGE_INDEX.link("drug-shortage", {"Generic Name": "ADALIMUMAB"})
    assert {link.confidence for link in found} == {"possible"}


RECALL_INDEX = ProductLinkIndex(
    [
        product("1807245616", "CIPROMAX 750MG TAB", ("CIPROFLOXACIN",)),
        product("1807245617", "CIPROMAX 500MG TAB", ("CIPROFLOXACIN HYDROCHLORIDE",)),
        product("1807245618", "DOPRAM 100 MG", ("DOXAPRAM",)),
        product("1807245619", "PENOPEN 250", ("PENICILLIN V",)),
    ]
)


def recall_link(trade_name: str, body: str = "") -> dict[str, tuple[str, str]]:
    detail = (("Body", body),) if body else ()
    found = RECALL_INDEX.link("drugs-circulars", {"Trade Name": trade_name}, detail)
    return {link.register_number: (link.confidence, link.reason) for link in found}


def test_a_recall_row_with_only_a_brand_is_possible() -> None:
    assert {k: v[0] for k, v in recall_link("Penopen 250 mg").items()} == {"1807245619": "possible"}


def test_a_recall_whose_text_names_the_substances_of_the_brand_is_matched() -> None:
    found = recall_link("Dopram 100 MG /5ML", "Trade Name Scientific Name Dopram DOXAPRAM")
    assert found["1807245618"][0] == "matched"


def test_a_recall_naming_the_register_number_matches_that_product_only() -> None:
    found = recall_link("Unrelated", "Register Number 1807245616 Affected batch 1141608")
    assert found == {"1807245616": ("matched", "register number named in the circular")}


def test_a_batch_number_is_not_mistaken_for_a_register_number() -> None:
    assert recall_link("Unrelated", "Affected batch number 1141608 1141609 160-212-02") == {}


def test_a_recall_with_an_unknown_brand_links_to_nothing() -> None:
    assert recall_link("Nothing at all", "DOXAPRAM") == {}


RMM_INDEX = ProductLinkIndex(
    [
        product("30", "RINVOQ 15 MG", ("UPADACITINIB",)),
        product("31", "RINVOQ", ("SOMETHING",)),
    ]
)


def test_a_risk_minimization_row_links_by_brand_and_scientific_name() -> None:
    found = RMM_INDEX.link("rmm", {"Scientific Name": "Upadacitinib", "Brand name": "Rinvoq"})
    assert {link.register_number: link.confidence for link in found} == {
        "30": "matched",
        "31": "possible",
    }


DHPC_INDEX = ProductLinkIndex(
    [
        product("40", "GILENYA 0.5 MG", ("FINGOLIMOD",)),
        product("41", "FEGONA", ("FINGOLIMOD",)),
        product("42", "MEGAMOX", ("AMOXICILLIN", "CLAVULANIC ACID")),
        product("43", "OTHERDRUG", ("DOMPERIDONE",)),
    ]
)


def dhpc_link(product_text: str) -> dict[str, str]:
    found = DHPC_INDEX.link("dhpc", {"Product": product_text})
    return {link.register_number: link.confidence for link in found}


def test_a_letter_naming_a_brand_and_its_substance_matches_that_brand() -> None:
    assert dhpc_link("Gilenya® - Fingolimod")["40"] == "matched"
    assert dhpc_link("Megamox (Amoxicillin / Clavulanic acid)")["42"] == "matched"


def test_a_letter_naming_only_a_substance_is_possible_for_every_product_with_it() -> None:
    assert dhpc_link("Fingolimod") == {"40": "possible", "41": "possible"}


def test_a_letter_naming_a_brand_without_its_substance_is_possible() -> None:
    assert dhpc_link("Gilenya®") == {"40": "possible"}


def test_a_letter_naming_a_brand_and_only_some_of_its_substances_is_possible() -> None:
    assert dhpc_link("Megamox (Amoxicillin)")["42"] == "possible"


def test_a_letter_that_names_nothing_known_links_to_nothing() -> None:
    assert dhpc_link("Apixaban, Edoxaban, Dabigatran and Rivaroxaban") == {}


STRENGTH_INDEX = ProductLinkIndex(
    [
        product("30", "ESOMA 20 MG CAPSULES", ("ESOMEPRAZOLE",)),
        product("31", "ESOMA 40 MG CAPSULES", ("ESOMEPRAZOLE",)),
        product("32", "FLUVAX", ("INFLUENZA VIRUS A", "INFLUENZA VIRUS B")),
    ]
)


def strength_link(trade_name: str, generic: str = "ESOMEPRAZOLE") -> dict[str, tuple[str, str]]:
    found = STRENGTH_INDEX.link(
        "drug-shortage", {"Generic Name": generic}, (("Trade name", trade_name),)
    )
    return {item.register_number: (item.confidence, item.reason) for item in found}


def test_a_shortage_that_names_one_strength_matches_only_that_strength() -> None:
    result = strength_link("ESOMA 20 MG DELAYED RELEASE CAPSULES")

    assert result["30"][0] == "matched"
    # the same brand in another strength is possible, never matched
    assert result["31"] == ("possible", "same trade name, a different strength or form")


def test_a_shortage_that_names_no_strength_is_only_possible_when_the_brand_has_several() -> None:
    result = strength_link("ESOMA")

    assert {k: v[0] for k, v in result.items()} == {"30": "possible", "31": "possible"}


def test_a_shortage_that_names_no_strength_matches_a_brand_with_one_product() -> None:
    index = ProductLinkIndex([product("50", "VEGA", ("SILDENAFIL",))])

    found = index.link("drug-shortage", {"Generic Name": "SILDENAFIL"}, (("Trade name", "VEGA"),))

    assert {item.register_number: item.confidence for item in found} == {"50": "matched"}


FORM_INDEX = ProductLinkIndex(
    [
        LinkableProduct.build(
            "60", "VIAGRA 50MG F.C TAB", ("SILDENAFIL",),
            strengths=["50"], dosage_form="Film-coated tablet",
        ),
        LinkableProduct.build(
            "61", "SINGULAIR", ("MONTELUKAST SODIUM",),
            strengths=["10"], dosage_form="Film-coated tablet",
        ),
        LinkableProduct.build(
            "62", "CECLOR 500MG CAPSULE", ("CEFACLOR",),
            strengths=["500"], dosage_form="Capsule, hard",
        ),
        LinkableProduct.build(
            "63", "PRODUCT WITHOUT NUMBERS", ("CEFACLOR",),
            strengths=["375"], dosage_form="Capsule, hard",
        ),
    ]
)  # fmt: skip


def form_link(generic: str, *trade_names: str) -> dict[str, tuple[str, str]]:
    found = FORM_INDEX.link(
        "drug-shortage", {"Generic Name": generic}, tuple(("Trade name", n) for n in trade_names)
    )
    return {item.register_number: (item.confidence, item.reason) for item in found}


def test_a_listed_orodispersible_tablet_is_not_a_film_coated_tablet_of_the_same_brand() -> None:
    result = form_link("SILDENAFIL", "VIAGRA 50 mg Orodispersible Tablet")

    assert result["60"][0] == "possible"


def test_the_same_brand_strength_and_form_is_a_match() -> None:
    assert form_link("SILDENAFIL", "VIAGRA 50 mg film-coated tablet")["60"][0] == "matched"


def test_a_brand_with_an_extra_word_that_names_another_product_is_not_the_brand() -> None:
    result = form_link("MONTELUKAST SODIUM", "SINGULAIR PAEDIATRIC 4 MG CHEWABLE TAB")

    assert result == {}


def test_the_registry_strength_is_used_when_the_trade_name_has_no_number() -> None:
    assert form_link("MONTELUKAST SODIUM", "SINGULAIR 10 MG FILM COATED TABLET")["61"][0] == (
        "matched"
    )
    assert form_link("MONTELUKAST SODIUM", "SINGULAIR 4 MG FILM COATED TABLET")["61"][0] == (
        "possible"
    )


def test_a_listed_strength_that_is_not_the_registered_strength_is_never_a_match() -> None:
    result = form_link("CEFACLOR", "CECLOR 250MG CAPSULE")

    assert result["62"] == ("possible", "same trade name, a different strength or form")


def test_a_combination_strength_must_match_each_ingredient_not_only_the_numbers_seen() -> None:
    # Real SFDA row: only "TENORYL PLUS 10 mg/5 mg TABLET" is listed. 5/5 and 10/10 are other
    # products: their numbers are a subset of {10, 5}, but not the same strengths.
    index = ProductLinkIndex(
        [
            LinkableProduct.build(
                "70", "TENORYL PLUS 5 mg/5 mg TABLET", ("AMLODIPINE", "PERINDOPRIL"),
                strengths=["5", "5"], dosage_form="Tablet",
            ),
            LinkableProduct.build(
                "71", "TENORYL PLUS 10 mg/10 mg TABLET", ("AMLODIPINE", "PERINDOPRIL"),
                strengths=["10", "10"], dosage_form="Tablet",
            ),
            LinkableProduct.build(
                "72", "TENORYL PLUS 10 mg/5 mg TABLET", ("AMLODIPINE", "PERINDOPRIL"),
                strengths=["10", "5"], dosage_form="Tablet",
            ),
        ]
    )  # fmt: skip

    found = index.link(
        "drug-shortage",
        {"Generic Name": "AMLODIPINE,PERINDOPRIL"},
        (("Trade name", "TENORYL PLUS 10 mg/5 mg TABLET"),),
    )

    assert {i.register_number: i.confidence for i in found} == {
        "70": "possible",
        "71": "possible",
        "72": "matched",
    }


def test_a_listed_pack_size_that_is_not_the_product_pack_is_never_a_match() -> None:
    # Real SFDA row: the 14-capsule packs are short; the 28-capsule packs are other registrations.
    index = ProductLinkIndex(
        [
            LinkableProduct.build(
                "80", "EZORA 40 MG GASTRO-RESISTANT HARD CAPSULES (28S)", ("ESOMEPRAZOLE",),
                strengths=["40"], dosage_form="Gastro-resistant capsule, hard",
            ),
            LinkableProduct.build(
                "81", "EZORA 40 MG GASTRO-RESISTANT HARD CAPSULES (14S)", ("ESOMEPRAZOLE",),
                strengths=["40"], dosage_form="Gastro-resistant capsule, hard",
            ),
            LinkableProduct.build(
                "82", "PLAXOTRIN 5 MG/ML CONCENTRATE FOR SOLUTION FOR INFUSION (10ml)",
                ("PACLITAXEL",), strengths=["5"], dosage_form="Concentrate for solution",
            ),
        ]
    )  # fmt: skip

    ezora = index.link(
        "drug-shortage",
        {"Generic Name": "ESOMEPRAZOLE"},
        (("Trade name", "EZORA 40 MG GASTRO-RESISTANT HARD CAPSULES (14S)"),),
    )
    plaxotrin = index.link(
        "drug-shortage",
        {"Generic Name": "PACLITAXEL"},
        (("Trade name", "PLAXOTRIN 5 MG/ML CONCENTRATE FOR SOLUTION FOR INFUSION (20 ml)"),),
    )

    assert {i.register_number: i.confidence for i in ezora} == {"80": "possible", "81": "matched"}
    assert {i.register_number: i.confidence for i in plaxotrin} == {"82": "possible"}


def test_a_shortage_of_a_brand_says_nothing_about_a_longer_brand_name() -> None:
    index = ProductLinkIndex(
        [
            product("40", "PANADOL 500 MG TABLET", ("PARACETAMOL",)),
            product("41", "PANADOL ADVANCE 500 MG", ("PARACETAMOL",)),
        ]
    )

    found = index.link(
        "drug-shortage", {"Generic Name": "PARACETAMOL"}, (("Trade name", "PANADOL 500 MG TABLET"),)
    )

    assert {item.register_number: item.confidence for item in found} == {"40": "matched"}


def test_a_concentration_per_another_volume_a_starter_pack_or_a_generic_name_is_not_a_match() -> (
    None
):
    # Real rows of the resolved list
    index = ProductLinkIndex(
        [
            LinkableProduct.build(
                "90", "ATROSOL 250 mcg/ml nebuliser solution", ("IPRATROPIUM BROMIDE",),
                strengths=["250"], dosage_form="Nebuliser solution",
            ),
            LinkableProduct.build(
                "91", "CHAMPIX 0.5 MG F-C TAB", ("VARENICLINE",),
                strengths=["0.5"], dosage_form="Film-coated tablet",
            ),
            LinkableProduct.build(
                "92", "DEXTROSE 5%", ("DEXTROSE",), strengths=["5"],
                dosage_form="Solution for infusion",
            ),
        ]
    )  # fmt: skip

    def found(generic: str, name: str) -> dict[str, str]:
        rows = index.link(
            "drug-shortage-resolved", {"Generic Name": generic}, (("Trade name", name),)
        )
        return {r.register_number: r.confidence for r in rows}

    assert found("IPRATROPIUM BROMIDE", "ATROSOL 250 mcg/2 ml nebuliser solution") == {
        "90": "possible"
    }
    assert found("VARENICLINE", "CHAMPIX 0.5 MG 11 tablets +1 MG 14 tablets") == {"91": "possible"}
    assert "matched" not in found("DEXTROSE", "5 % w/v DEXTROSE Injection 500 ml").values()


def test_the_only_product_named_after_its_substance_that_fits_the_row_is_a_match() -> None:
    index = ProductLinkIndex(
        [
            LinkableProduct.build(
                "95", "CYTARABINE 100MG-1ML VIAL", ("CYTARABINE",), strengths=["100"],
                dosage_form="Solution for injection",
            ),
            LinkableProduct.build(
                "96", "CYTARABINE 500MG-5ML VIAL", ("CYTARABINE",), strengths=["500"],
                dosage_form="Solution for injection",
            ),
        ]
    )  # fmt: skip

    rows = index.link(
        "drug-shortage",
        {"Generic Name": "CYTARABINE"},
        (("Trade name", "CYTARABINE 100MG-1ML VIAL"),),
    )

    assert {r.register_number: r.confidence for r in rows} == {"95": "matched", "96": "possible"}


def test_a_generic_name_written_once_per_maker_matches_that_many_products() -> None:
    def vial(number: str) -> LinkableProduct:
        return LinkableProduct.build(
            number, "CYTARABINE 100MG-1ML VIAL", ("CYTARABINE",), strengths=["100"],
            dosage_form="Solution for injection",
        )  # fmt: skip

    index = ProductLinkIndex([vial("97"), vial("98")])
    once = index.link(
        "drug-shortage",
        {"Generic Name": "CYTARABINE"},
        (("Trade name", "CYTARABINE 100MG-1ML VIAL"),),
    )
    twice = index.link(
        "drug-shortage",
        {"Generic Name": "CYTARABINE"},
        (("Trade name", "CYTARABINE 100MG-1ML VIAL"), ("Trade name", "CYTARABINE 100MG-1ML VIAL")),
    )

    assert {r.confidence for r in once} == {"possible"}
    assert {r.confidence for r in twice} == {"matched"}
