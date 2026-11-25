"""Read MeDIC's contraindication list (a spreadsheet) into drug-disease records.

MeDIC (Medicines, Diseases, Indications and Contraindications, RENCI) collects what government
drug labels (US, EU, Japan) say a drug must not be used with. One row per drug and disease, with
the label text it came from. The file is an `.xlsx` with inline strings, so the standard library
reads it: no spreadsheet package is needed.
"""

import re
import zipfile
from pathlib import Path

from defusedxml import ElementTree as SafeET

from pharmavique.interactions.domain.names import base_key
from pharmavique.interactions.domain.records import ContraindicationRecord

SOURCE = "medic"
_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COLUMN = re.compile(r"[A-Z]+")


def _rows(path: Path) -> list[dict[str, str]]:
    """Every row of the first sheet as {header: text}."""
    with zipfile.ZipFile(path) as archive:
        # our own download of a public release file, but parsed as if it were not: entity
        # declarations (how an XML bomb is built) are refused
        sheet = SafeET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    table: list[dict[str, str]] = []
    for row in sheet.iter(f"{_MAIN}row"):
        cells: dict[str, str] = {}
        for cell in row.findall(f"{_MAIN}c"):
            match = _COLUMN.match(cell.get("r", ""))
            if match is None:
                continue
            inline = cell.find(f"{_MAIN}is")
            value = cell.find(f"{_MAIN}v")
            if inline is not None:
                text = "".join(t.text or "" for t in inline.iter(f"{_MAIN}t"))
            else:
                text = value.text or "" if value is not None else ""
            cells[match.group(0)] = text.strip()
        table.append(cells)
    return table


def read_contraindications(path: Path) -> list[ContraindicationRecord]:
    table = _rows(path)
    if not table:
        return []
    names = table[0]
    records: dict[tuple[str, str], ContraindicationRecord] = {}
    for row in table[1:]:
        named = {names[column]: value for column, value in row.items() if column in names}
        ingredient = base_key(
            named.get("active ingredient") or named.get("final normalized drug label") or ""
        )
        disease = (named.get("final normalized disease label") or "").strip().lower()
        if not ingredient or not disease:
            continue
        records.setdefault(
            (ingredient, disease),
            ContraindicationRecord(
                ingredient=ingredient,
                disease=disease,
                disease_id=named.get("final normalized disease id") or "",
                text=named.get("contraindications", ""),
                source=SOURCE,
            ),
        )
    return list(records.values())
