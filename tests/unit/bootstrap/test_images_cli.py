"""The picture commands that need no network: reading products, writing the search phrases."""

import json
from pathlib import Path

import pytest

from pharmavique.bootstrap.cli import build_parser, main
from pharmavique.bootstrap.images import load_product_refs
from pharmavique.shared_kernel.market import Market


def write_products(path: Path) -> None:
    rows = [
        {
            "market": "SA",
            "register_number": "1-1",
            "trade_name_en": "PANADOL Extra",
            "trade_name_ar": "بنادول اكسترا",
            "ingredients": [
                {"name": "PARACETAMOL", "strength": "500.000", "unit": "mg"},
                {"name": "CAFFEINE", "strength": "65", "unit": "mg"},
                {"name": "WATER", "strength": None, "unit": None},
            ],
            "dosage_form_en": "Tablet",
            "company": "GlaxoSmithKline",
        },
        {
            "market": "SA",
            "register_number": "2-2",
            "trade_name_en": None,
            "trade_name_ar": None,
            "ingredients": [],
            "dosage_form_en": None,
            "company": None,
        },
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def test_products_become_references_with_registry_strengths(tmp_path: Path) -> None:
    path = tmp_path / "products.jsonl"
    write_products(path)

    refs = load_product_refs(path)

    first = refs[0]
    assert (first.market, first.register_number) == (Market.SA, "1-1")
    assert first.trade_name_en == "PANADOL Extra"
    assert first.ingredient_names == ("PARACETAMOL", "CAFFEINE", "WATER")
    assert first.strengths == ("500 mg", "65 mg")
    assert first.marketing_company == "GlaxoSmithKline"


def test_the_queries_command_writes_phrases_only_for_products_that_have_a_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    products = tmp_path / "products.jsonl"
    write_products(products)
    out = tmp_path / "queries.json"

    code = main(
        ["sfda-images-queries", "--products", str(products), "--out", str(out), "--limit", "10"]
    )

    written = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert set(written) == {"1-1"}
    assert "PANADOL Extra PARACETAMOL Saudi Arabia" in written["1-1"]
    assert "1 products" in capsys.readouterr().out


def test_limit_and_offset_pick_a_slice_of_the_products(tmp_path: Path) -> None:
    products = tmp_path / "products.jsonl"
    rows: list[dict[str, object]] = [
        {
            "market": "SA",
            "register_number": f"1-{n}",
            "trade_name_en": f"DRUG{n}",
            "trade_name_ar": None,
            "ingredients": [],
            "dosage_form_en": None,
            "company": None,
        }
        for n in range(5)
    ]
    products.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = tmp_path / "queries.json"

    main(
        [
            "sfda-images-queries",
            "--products",
            str(products),
            "--out",
            str(out),
            "--offset",
            "2",
            "--limit",
            "2",
        ]
    )

    assert set(json.loads(out.read_text(encoding="utf-8"))) == {"1-2", "1-3"}


def test_a_missing_products_file_is_explained_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["sfda-images-queries", "--products", str(tmp_path / "nope.jsonl")])

    assert code == 4
    assert "sfda-images-export" in capsys.readouterr().err


def test_the_fetch_command_is_polite_by_default() -> None:
    args = build_parser().parse_args(["sfda-images", "--results", "r.json"])

    assert args.delay >= 1.0
    assert args.out == "data/media"
