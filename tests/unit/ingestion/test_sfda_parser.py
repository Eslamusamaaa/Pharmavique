"""Parser tests run on synthetic HTML shaped like the SFDA public pages (no real drug data)."""

import pytest

from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import (
    ParseError,
    parse_details_page,
    parse_list_page,
)

LIST_HTML = """
<html><body>
<table class="views-table">
  <thead><tr>
    <th>Scientific Name</th><th>Trade Name</th><th>Strength</th>
    <th>Doesage Form</th><th>Price</th><th>Details</th>
  </tr></thead>
  <tbody>
    <tr class="odd">
      <td>ACMEDRONE</td><td>ACME-ONE 5MG TAB</td><td>5</td><td>Tablet</td><td>12.5</td>
      <td><a href="/en/details_data?nid=1&amp;id=1-111-22&amp;page=0">Details</a></td>
    </tr>
    <tr class="even">
      <td> FOO , BAR </td><td>FOOBAR  COMBO</td><td>0.5,2</td><td>Oral solution</td><td></td>
      <td><a href="/en/details_data?nid=1&amp;id=0000099999&amp;page=0">Details</a></td>
    </tr>
  </tbody>
</table>
<nav><ul class="pager">
  <li><span>1</span></li>
  <li><a href="?page=1">2</a></li>
  <li><a href="?page=2">3</a></li>
  <li><a href="?page=41">last</a></li>
</ul></nav>
<a href="/en/details_data?nid=1&amp;id=zzz&amp;page=0">not a pager link</a>
</body></html>
"""

DETAILS_HTML = """
<html><body><table><tbody>
<tr><th>Register Number</th><td>1-111-22</td></tr>
<tr><th>Trade Name</th><td>  ACME-ONE   5MG TAB </td></tr>
<tr><th>Manufacturers</th><td>Name: Maker A | Country: Atlantis<br />
Name: Maker B | Country: Mu</td></tr>
<tr><th>ATC Code 2</th><td></td></tr>
<tr><th>Price</th><td>12.5</td></tr>
<tr><th>Price</th><td>13</td></tr>
</tbody></table></body></html>
"""


def test_list_rows_are_mapped_by_header_name() -> None:
    page = parse_list_page(LIST_HTML)

    first = page.rows[0]
    assert first.scientific_name == "ACMEDRONE"
    assert first.trade_name == "ACME-ONE 5MG TAB"
    assert first.strength == "5"
    assert first.dosage_form == "Tablet"
    assert first.price == "12.5"
    assert first.registration_key == "1-111-22"
    assert first.details_href == "/en/details_data?nid=1&id=1-111-22&page=0"


def test_list_cells_are_whitespace_normalized_and_empty_cells_stay_empty() -> None:
    second = parse_list_page(LIST_HTML).rows[1]

    assert second.scientific_name == "FOO , BAR"
    assert second.trade_name == "FOOBAR COMBO"
    assert second.strength == "0.5,2"
    assert second.price == ""
    assert second.registration_key == "0000099999"


def test_last_page_comes_from_pager_links_only() -> None:
    assert parse_list_page(LIST_HTML).last_page == 41


def test_list_page_without_pager_has_no_last_page() -> None:
    html = LIST_HTML.split("<nav>")[0] + "</body></html>"

    assert parse_list_page(html).last_page is None


def test_empty_list_table_gives_no_rows() -> None:
    html = """<table><thead><tr><th>Scientific Name</th><th>Trade Name</th><th>Strength</th>
    <th>Dosage Form</th><th>Price</th><th>Details</th></tr></thead><tbody></tbody></table>"""

    assert parse_list_page(html).rows == ()


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><h1>Access denied</h1></body></html>",  # block page, no table
        "<table><tr><th>Name</th><th>Other</th></tr></table>",  # unknown headers
    ],
)
def test_unexpected_list_page_raises_instead_of_returning_nothing(html: str) -> None:
    with pytest.raises(ParseError):
        parse_list_page(html)


def test_list_row_with_wrong_cell_count_raises() -> None:
    html = """<table><thead><tr><th>Scientific Name</th><th>Trade Name</th><th>Strength</th>
    <th>Dosage Form</th><th>Price</th><th>Details</th></tr></thead>
    <tbody><tr><td>ONLY</td><td>TWO</td></tr></tbody></table>"""

    with pytest.raises(ParseError):
        parse_list_page(html)


def test_list_row_without_a_details_id_raises() -> None:
    html = """<table><thead><tr><th>Scientific Name</th><th>Trade Name</th><th>Strength</th>
    <th>Dosage Form</th><th>Price</th><th>Details</th></tr></thead>
    <tbody><tr><td>A</td><td>B</td><td>1</td><td>C</td><td>2</td>
    <td><a href="/en/details_data?nid=1">Details</a></td></tr></tbody></table>"""

    with pytest.raises(ParseError):
        parse_list_page(html)


def test_details_keep_every_label_in_page_order() -> None:
    page = parse_details_page(DETAILS_HTML)

    assert [f.label for f in page.fields] == [
        "Register Number",
        "Trade Name",
        "Manufacturers",
        "ATC Code 2",
        "Price",
        "Price",
    ]


def test_details_values_are_whitespace_normalized() -> None:
    fields = {f.label: f for f in parse_details_page(DETAILS_HTML).fields}

    assert fields["Trade Name"].value == "ACME-ONE 5MG TAB"
    assert fields["ATC Code 2"].value == ""


def test_multi_line_cells_are_split_on_line_breaks() -> None:
    manufacturers = next(
        f for f in parse_details_page(DETAILS_HTML).fields if f.label == "Manufacturers"
    )

    assert manufacturers.lines == (
        "Name: Maker A | Country: Atlantis",
        "Name: Maker B | Country: Mu",
    )
    assert manufacturers.value == "Name: Maker A | Country: Atlantis\nName: Maker B | Country: Mu"


def test_arabic_labels_parse_the_same_way() -> None:
    html = (
        "<table><tr><th>رقم التسجيل</th><td>1-111-22</td></tr>"
        "<tr><th>السعر</th><td>12.5</td></tr></table>"
    )

    fields = parse_details_page(html).fields

    assert [(f.label, f.value) for f in fields] == [("رقم التسجيل", "1-111-22"), ("السعر", "12.5")]


@pytest.mark.parametrize(
    "html",
    ["<html><body>Please verify you are human</body></html>", "<table><tr><td>x</td></tr></table>"],
)
def test_details_page_without_label_value_rows_raises(html: str) -> None:
    with pytest.raises(ParseError):
        parse_details_page(html)
