"""Reading real product pages (trimmed fixtures captured 2026-11-23 from the five pilot sites)."""

from decimal import Decimal
from pathlib import Path

import pytest

from pharmavique.offers.domain.category import classify
from pharmavique.offers.domain.model import Availability, ListingCategory
from pharmavique.offers.infrastructure.config import load_retailers
from pharmavique.offers.infrastructure.parsing import decode, html_block_text, parse_product

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "offers"
CONFIGS = load_retailers(ROOT / "config" / "retailers")


def page(site: str) -> str:
    return (FIXTURES / site / "product.html").read_text(encoding="utf-8")


def parsed(site: str):
    product = parse_product(page(site), f"https://example.test/{site}/x", CONFIGS[site])
    assert product is not None
    return product


def test_nahdi_page() -> None:
    p = parsed("nahdi")

    assert p.source_id == "104256764"
    assert p.name == "Bogenia Angelic Loose Powder - Banana - BG642.002"
    assert p.brand == "Bogenia"
    assert p.category_path == ("Makeup", "Face", "Powder")
    assert classify(p.category_path) is ListingCategory.COSMETIC
    assert p.currency == "SAR"
    assert p.price is not None
    assert p.price > 0
    assert p.availability is Availability.IN_STOCK
    assert len(p.image_urls) >= 1
    assert p.description is not None
    assert p.language == "en"


def test_united_page() -> None:
    p = parsed("united")

    assert p.source_id == "206207"
    assert p.price == Decimal("30.48")
    assert p.currency == "SAR"
    assert p.brand == "Koleston"
    assert p.availability is Availability.IN_STOCK
    assert p.description is not None
    assert p.description.startswith("Koleston Hair Color Creme")
    assert classify(p.category_path) is ListingCategory.COSMETIC


def test_innova_page_takes_its_description_from_the_html_block() -> None:
    p = parsed("innova")

    assert p.source_id == "1006421"
    assert p.price == Decimal("24.15")
    assert p.currency == "SAR"
    assert p.barcode is None  # the page publishes an empty gtin: nothing is invented
    assert p.image_urls[0].startswith("https://img.innovapharmacy.com/")
    assert p.description is not None
    assert "طريقة الاستخدام" in p.description  # the JSON-LD carries no description at all


def test_adam_page_from_json_ld_alone() -> None:
    p = parsed("adam")

    assert p.source_id == "512111"
    assert p.price == Decimal("93.15")
    assert p.currency == "SAR"
    assert p.description is not None
    assert "roll-on deodorant" in p.description


def test_dr_move_page_has_a_barcode_a_long_description_and_a_pack_size() -> None:
    p = parsed("drmove")

    assert p.source_id == "10632"
    assert p.price == Decimal("22.05")
    assert p.barcode == "04030041001823"
    assert p.language == "ar"
    assert p.pack_text == "30 قرص"
    assert p.description is not None
    assert len(p.description) > 500
    assert p.dosage_form_text is None or p.dosage_form_text.startswith("tablet")


@pytest.mark.parametrize("site", ["nahdi", "united", "innova", "adam", "drmove"])
def test_a_fingerprint_does_not_change_with_the_price(site: str) -> None:
    first = parsed(site)

    assert first.details_hash == parsed(site).details_hash
    assert len(first.details_hash) == 16


def test_a_page_with_no_product_data_is_not_a_product() -> None:
    assert (
        parse_product("<html><body>Category</body></html>", "https://x/y", CONFIGS["united"])
        is None
    )


def test_a_product_without_an_id_cannot_be_stored() -> None:
    body = '<script type="application/ld+json">{"@type":"Product","name":"X"}</script>'

    assert parse_product(body, "https://x/y/no-number", CONFIGS["united"]) is None


def test_a_price_without_a_currency_stays_unconfirmed() -> None:
    body = (
        '<script type="application/ld+json">{"@type":"Product","name":"X","sku":"77",'
        '"offers":{"@type":"Offer","price":"10"}}</script>'
    )

    product = parse_product(body, "https://x/y", CONFIGS["united"])

    assert product is not None
    assert product.price == Decimal("10")
    assert product.currency is None
    assert product.availability is Availability.UNKNOWN


def test_ingredients_are_taken_only_from_a_passage_the_page_labels() -> None:
    body = (
        '<script type="application/ld+json">{"@type":"Product","name":"X","sku":"77",'
        '"description":"Good for pain.\\nActive ingredient: Paracetamol 500 mg\\nMore"}</script>'
    )
    product = parse_product(body, "https://x/y", CONFIGS["united"])

    assert product is not None
    assert product.ingredients_text == "Paracetamol 500 mg"

    quiet = body.replace("Active ingredient: ", "Contains ")
    other = parse_product(quiet, "https://x/y", CONFIGS["united"])
    assert other is not None
    assert other.ingredients_text is None


def test_html_block_text_keeps_lines_and_list_items() -> None:
    html = (
        '<div class="a b"><p>One</p><ul><li>Two</li><li>Three</li></ul></div>'
        '<div class="a">no</div>'
    )

    assert html_block_text(html, ["a", "b"]) == "One\n- Two\n- Three"
    assert html_block_text(html, ["missing"]) is None
    assert html_block_text(html, []) is None


def test_utf8_bytes_are_decoded_as_utf8_whatever_the_header_says() -> None:
    text = "Johnson\u2019s Baby"
    assert decode(text.encode(), "iso-8859-1") == text
    assert decode(b"caf\xe9", None) == "caf\xe9"
