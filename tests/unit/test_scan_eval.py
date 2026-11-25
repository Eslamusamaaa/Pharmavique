"""The scan evaluation tool: its drawing, its brand comparison and its label file."""

import importlib.util
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

from pharmavique.recognition.domain.scans import ScanKind

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scan_eval.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("scan_eval", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["scan_eval"] = module
    spec.loader.exec_module(module)
    return module


def items(tool, count: int):
    names = ["PANADOL EXTRA 500MG TAB", "BRUFEN 400 MG", "AUGMENTIN 625 MG TAB", "CONCOR 5 MG",
             "VOLTAREN 50 MG TAB", "NEXIUM 40MG", "ZYRTEC 10 MG", "LIPITOR 20MG"]  # fmt: skip
    return [tool.Item(str(i), n, tool.brand_of(n)) for i, n in enumerate(names[:count])]


@pytest.mark.parametrize(
    ("kind", "count", "size"),
    [
        (ScanKind.BOX, 1, (900, 600)),
        (ScanKind.PRESCRIPTION, 4, (1000, 1300)),
        (ScanKind.SHELF, 8, (1600, 1000)),
    ],
)
def test_each_kind_of_picture_is_drawn_as_a_real_png(tool, kind, count, size) -> None:
    import random

    data = tool.make_picture(kind, items(tool, count), random.Random(1))  # noqa: S311

    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG"
    assert image.size == size


def test_a_brand_matches_however_the_model_wrote_the_rest(tool) -> None:
    brand = tool.brand_of("PANADOL EXTRA 500MG TAB")

    assert tool.same_brand("Panadol Extra", brand)
    assert tool.same_brand("PANADOL EXTRA 500 mg tablets", brand)
    assert not tool.same_brand("BRUFEN 400", brand)
    assert not tool.same_brand("", brand)


def test_the_label_file_gives_the_register_numbers_of_each_picture(tool, tmp_path: Path) -> None:
    (tmp_path / "labels.csv").write_text(
        "file,register_numbers\nshelf1.jpg,0902221712;0211234420\nbox.png,1802256914\n",
        encoding="utf-8",
    )

    rows = tool.read_labels(tmp_path)

    assert rows == [
        (tmp_path / "shelf1.jpg", ["0902221712", "0211234420"]),
        (tmp_path / "box.png", ["1802256914"]),
    ]


def test_the_tally_reports_nothing_expected_without_dividing_by_zero(tool, capsys) -> None:
    tool.report(ScanKind.BOX, tool.Tally())

    assert "n/a" in capsys.readouterr().out


# ---- real photos: labels with their source, failure cases, the confidence trade-off -----------


def test_the_committed_label_file_carries_kind_source_and_notes(tool, tmp_path: Path) -> None:
    labels = tmp_path / "labels.csv"
    labels.write_text(
        "file,kind,register_numbers,source_url,notes\n"
        "box1.jpg,box,0902221712,https://example.test/post/1,dim light\n"
        "rx1.jpg,prescription,0902221712;1802256914,,printed\n",
        encoding="utf-8",
    )

    rows = tool.read_label_rows(labels)

    assert [r.file for r in rows] == ["box1.jpg", "rx1.jpg"]
    assert rows[0].kind == "box"
    assert rows[0].numbers == ["0902221712"]
    assert rows[0].source_url == "https://example.test/post/1"
    assert rows[1].numbers == ["0902221712", "1802256914"]
    assert rows[1].source_url == ""


def test_a_label_file_without_the_optional_columns_still_reads(tool, tmp_path: Path) -> None:
    labels = tmp_path / "labels.csv"
    labels.write_text("file,register_numbers\nbox1.jpg,1\n", encoding="utf-8")

    (row,) = tool.read_label_rows(labels)

    assert (row.kind, row.source_url, row.notes) == ("", "", "")


def test_a_label_file_that_names_a_person_column_is_refused(tool, tmp_path: Path) -> None:
    labels = tmp_path / "labels.csv"
    labels.write_text("file,register_numbers,patient_name\nbox1.jpg,1,Ahmed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="patient"):
        tool.read_label_rows(labels)


def test_the_sweep_shows_how_many_lines_each_threshold_calls_confident_and_how_many_are_right(
    tool,
) -> None:
    scored = [(0.97, True), (0.95, True), (0.72, True), (0.6, False), (0.4, False)]

    rows = {row["threshold"]: row for row in tool.sweep(scored, (0.5, 0.9))}

    assert rows[0.9] == {
        "threshold": 0.9,
        "confident": 2,
        "confident_right": 2,
        "uncertain": 3,
        "uncertain_right": 1,
    }
    assert rows[0.5]["confident"] == 4
    assert rows[0.5]["confident_right"] == 3


def make_scanner(tool, lines, candidates):
    from pharmavique.recognition.application.scan import ScanImage

    class Reader:
        async def read(self, image, media_type, kind):
            return lines

    class Finder:
        async def find(self, query, limit):
            return candidates

    return ScanImage(Reader(), Finder())


async def test_a_picture_gives_failure_cases_for_a_missed_name_a_wrong_product_and_an_extra_line(
    tool,
) -> None:
    from pharmavique.recognition.domain.scans import ExtractedLine, MatchCandidate

    scanner = make_scanner(
        tool,
        [
            ExtractedLine("Panadol Extra", "Panadol Extra", None, None),
            ExtractedLine("Mystery", "Mystery", None, None),
        ],
        [MatchCandidate("999", "x", "OTHER", 0.6)],
    )
    expected = [
        tool.Item("1", "PANADOL EXTRA 500MG TAB", tool.brand_of("PANADOL EXTRA 500MG TAB")),
        tool.Item("2", "BRUFEN 400 MG", tool.brand_of("BRUFEN 400 MG")),
    ]
    tally = tool.Tally()

    await tool.evaluate(scanner, ScanKind.BOX, b"x", "image/png", expected, tally, "box1.jpg")

    kinds = sorted(case["problem"] for case in tally.cases)
    assert kinds == ["extra_line", "name_not_read", "wrong_product"]
    wrong = next(c for c in tally.cases if c["problem"] == "wrong_product")
    assert wrong["file"] == "box1.jpg"
    assert wrong["expected"] == "1"
    assert wrong["top3"] == ["999"]
    assert tally.scored == [(0.6, False)]


def test_the_report_file_holds_numbers_and_failure_cases_but_no_image_or_text(
    tool, tmp_path: Path
) -> None:
    tally = tool.Tally(expected=2, read=1, top1=1, top3=1)
    tally.scored = [(0.95, True)]
    tally.cases = [{"file": "box1.jpg", "problem": "name_not_read", "expected": "2"}]
    out = tmp_path / "result.json"

    tool.write_report(out, ScanKind.BOX, tally, photos=3, labelled_by="the owner")

    import json

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["kind"] == "box"
    assert data["photos"] == 3
    assert data["labelled_by"] == "the owner"
    assert data["metrics"]["expected"] == 2
    assert data["cases"] == tally.cases
    assert data["sweep"]
