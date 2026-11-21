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
