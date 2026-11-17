"""The generic parser reads any SFDA table list. The HTML is synthetic, shaped like real pages."""

import pytest

from pharmavique.ingestion.infrastructure.connectors.sfda_web.generic_list import (
    parse_generic_page,
)
from pharmavique.ingestion.infrastructure.connectors.sfda_web.parser import ParseError

PAGER = (
    '<ul><li class="page-item active"><span class="page-link">3</span></li>'
    '<li><a href="?page=3">4</a></li><li><a href="?page=71">last</a></li></ul>'
)


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{PAGER}"


def test_headers_and_cells_are_read_in_column_order() -> None:
    html = table(["Pharmacy Name", "Region"], [["Alpha", "Mecca"], ["Beta", "Riyadh"]])

    page = parse_generic_page(html)

    assert page.headers == ("Pharmacy Name", "Region")
    assert [dict(row.cells) for row in page.rows] == [
        {"Pharmacy Name": "Alpha", "Region": "Mecca"},
        {"Pharmacy Name": "Beta", "Region": "Riyadh"},
    ]


def test_the_pager_gives_the_current_and_last_page() -> None:
    page = parse_generic_page(table(["A"], [["x"]]))

    assert (page.current_page, page.last_page) == (2, 71)


def test_cells_are_whitespace_normalized() -> None:
    page = parse_generic_page(table(["Name"], [["  Alpha \n  Beta  "]]))

    assert dict(page.rows[0].cells)["Name"] == "Alpha Beta"


def test_arabic_headers_and_values_are_kept_as_written() -> None:
    page = parse_generic_page(
        table(["اسم المكون العلمي", "رقم المكون"], [["Sodium", "16143-80-9"]])
    )

    assert dict(page.rows[0].cells) == {"اسم المكون العلمي": "Sodium", "رقم المكون": "16143-80-9"}


def test_a_details_column_becomes_the_row_link_and_is_not_a_data_column() -> None:
    html = table(
        ["Trade Name", "Details"],
        [["X", '<a href="/en/details_data?nid=1&amp;id=1161&amp;page=0">Details</a>']],
    )

    page = parse_generic_page(html)

    assert [dict(r.cells) for r in page.rows] == [{"Trade Name": "X"}]
    assert page.rows[0].link == "/en/details_data?nid=1&id=1161&page=0"


def test_the_key_is_the_id_parameter_of_a_details_link() -> None:
    html = table(
        ["Trade Name", "Details"],
        [["X", '<a href="/en/details_data?nid=1&amp;id=P-3-N-010112-4&amp;page=0">Details</a>']],
    )

    assert parse_generic_page(html).rows[0].key == "P-3-N-010112-4"


def test_the_key_of_a_percent_encoded_id_is_decoded() -> None:
    html = table(
        ["Name", "Details"],
        [["X", '<a href="/en/details_data?nid=1&amp;id=%20CALCIUM%20CHLORIDE%2CX">Details</a>']],
    )

    assert parse_generic_page(html).rows[0].key == "CALCIUM CHLORIDE,X"


def test_without_an_id_the_key_is_the_link_path() -> None:
    html = table(["Name", "Link"], [["X", '<a href="/en/node/17903?x=1">View</a>']])

    assert parse_generic_page(html).rows[0].key == "/en/node/17903"


def test_without_any_link_the_key_is_a_stable_hash_of_the_row_content() -> None:
    first = parse_generic_page(table(["Name", "Region"], [["Alpha", "Mecca"]])).rows[0]
    again = parse_generic_page(table(["Name", "Region"], [["Alpha", "Mecca"]])).rows[0]
    other = parse_generic_page(table(["Name", "Region"], [["Alpha", "Riyadh"]])).rows[0]

    assert first.key == again.key
    assert first.key != other.key
    assert first.link is None


def test_an_empty_table_gives_no_rows_but_keeps_the_headers() -> None:
    page = parse_generic_page(table(["Name"], []))

    assert page.rows == ()
    assert page.headers == ("Name",)


def test_a_blank_header_gets_a_positional_name() -> None:
    page = parse_generic_page(table(["#", ""], [["1", "Title"]]))

    assert page.headers == ("#", "col2")


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><h1>Access denied</h1></body></html>",
        "<table><tr><td>no headers at all</td></tr></table>",
    ],
)
def test_a_page_that_is_not_a_list_raises_instead_of_returning_nothing(html: str) -> None:
    with pytest.raises(ParseError):
        parse_generic_page(html)


def test_a_row_with_the_wrong_number_of_cells_raises() -> None:
    html = (
        "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
        "<tbody><tr><td>1</td></tr></tbody></table>"
    )

    with pytest.raises(ParseError):
        parse_generic_page(html)
