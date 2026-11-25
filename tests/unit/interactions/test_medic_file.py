"""Reading MeDIC's contraindication spreadsheet (inline-string .xlsx) into records."""

import zipfile
from pathlib import Path

import pytest

from pharmavique.interactions.infrastructure.medic import read_contraindications

HEAD = [
    "active ingredient",
    "contraindications",
    "final normalized disease id",
    "final normalized disease label",
    "final normalized drug label",
]
CONTENT_TYPES = (
    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/></Types>'
)


def column(index: int) -> str:
    return "ABCDEFGHIJ"[index]


def write_xlsx(path: Path, rows: list[list[str]]) -> None:
    body = ""
    for number, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{column(i)}{number}" t="inlineStr"><is><t>{value}</t></is></c>'
            for i, value in enumerate(row)
        )
        body += f'<row r="{number}">{cells}</row>'
    sheet = (
        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def test_rows_become_records_keyed_by_the_normalized_ingredient(tmp_path: Path) -> None:
    file = tmp_path / "c.xlsx"
    write_xlsx(
        file,
        [
            HEAD,
            ["metolazone", "Anuria, hepatic coma.", "MONDO:1", "anuria", "Metolazone"],
            ["Warfarin Sodium", "Pregnancy.", "MONDO:2", "pregnancy", "Warfarin"],
        ],
    )

    records = read_contraindications(file)

    assert [(r.ingredient, r.disease, r.disease_id) for r in records] == [
        ("metolazone", "anuria", "MONDO:1"),
        ("warfarin", "pregnancy", "MONDO:2"),
    ]
    assert records[0].text == "Anuria, hepatic coma."


def test_the_same_ingredient_and_disease_is_kept_once_and_unfinished_rows_are_skipped(
    tmp_path: Path,
) -> None:
    file = tmp_path / "c.xlsx"
    write_xlsx(
        file,
        [
            HEAD,
            ["metolazone", "Text one.", "MONDO:1", "anuria", "Metolazone"],
            ["metolazone", "Text two.", "MONDO:1", "anuria", "Metolazone"],
            ["metolazone", "No disease.", "", "", "Metolazone"],
            ["", "No drug.", "MONDO:3", "asthma", ""],
        ],
    )

    records = read_contraindications(file)

    assert [(r.ingredient, r.disease, r.text) for r in records] == [
        ("metolazone", "anuria", "Text one.")
    ]


def test_a_sheet_that_declares_entities_is_refused(tmp_path: Path) -> None:
    """An entity declaration is how an XML bomb is built: a downloaded file must not be able to use
    one, even though our own download is trusted today (bandit B314)."""
    sheet = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE worksheet [<!ENTITY a "aaaaaaaaaa">]>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&a;</t></is></c></row></sheetData>'
        "</worksheet>"
    )
    file = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)

    with pytest.raises(ValueError, match=r"[Ee]ntit"):
        read_contraindications(file)
