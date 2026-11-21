"""Reading DDInter's downloadable CSV files into interaction records."""

from pathlib import Path

from pharmavique.interactions.domain.severity import Severity
from pharmavique.interactions.infrastructure.ddinter import read_ddinter

HEADER = "DDInterID_A,Drug_A,DDInterID_B,Drug_B,Level\n"


def write(folder: Path, name: str, *rows: str) -> None:
    (folder / name).write_text(HEADER + "".join(row + "\n" for row in rows), encoding="utf-8")


def test_a_row_becomes_a_record_with_sorted_normalized_names_and_the_source_name(
    tmp_path: Path,
) -> None:
    write(tmp_path, "a.csv", "DDInter975,Iron,DDInter582,Dolutegravir,Major")

    records = read_ddinter(tmp_path)

    assert [(r.ingredient_a, r.ingredient_b, r.severity, r.source) for r in records] == [
        ("dolutegravir", "iron", Severity.MAJOR, "ddinter-2.0")
    ]


def test_the_same_pair_in_two_files_is_one_record_with_the_higher_severity(
    tmp_path: Path,
) -> None:
    write(tmp_path, "a.csv", "D1,Warfarin,D2,Aspirin,Moderate")
    write(tmp_path, "b.csv", "D2,Aspirin,D1,Warfarin,Major")

    records = read_ddinter(tmp_path)

    assert [(r.ingredient_a, r.ingredient_b, r.severity) for r in records] == [
        ("aspirin", "warfarin", Severity.MAJOR)
    ]


def test_unrated_rows_are_kept_as_unknown_and_junk_rows_are_skipped(tmp_path: Path) -> None:
    write(
        tmp_path,
        "a.csv",
        "D1,Alpha,D2,Beta,Unknown",
        "D3,Gamma,D3,Gamma,Major",  # a drug with itself
        "D4,,D5,Delta,Minor",  # a missing name
    )

    records = read_ddinter(tmp_path)

    assert [(r.ingredient_a, r.ingredient_b, r.severity) for r in records] == [
        ("alpha", "beta", Severity.UNKNOWN)
    ]
