"""The picture commands that need no network: reading products, writing the search phrases."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pharmavique.bootstrap.cli import build_parser, main
from pharmavique.bootstrap.images import export_new_products, load_product_refs
from pharmavique.ingestion.application.ports import FetchedPage
from pharmavique.ingestion.infrastructure.connectors.sfda_web.store import SnapshotStore
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


def _image_row(number: str, status: str) -> dict[str, object]:
    return {
        "market": "SA",
        "register_number": number,
        "image_url": f"https://shop.example.sa/{number}.jpg",
        "page_url": "https://shop.example.sa/p",
        "query": "q",
        "status": status,
        "score": 0.8,
        "signals": ["name"],
        "content_hash": number * 8,
        "content_type": "image/jpeg",
        "size_bytes": 2000,
        "storage_key": f"products/SA/{number}/x.jpg",
        "provenance": {
            "source": "web-image-search",
            "source_ref": "https://shop.example.sa/p",
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "snapshot_id": "r",
            "trust": "unofficial_unverified",
        },
    }


def test_the_report_counts_coverage_and_lists_products_without_a_picture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    products = tmp_path / "products.jsonl"
    rows: list[dict[str, object]] = [
        {"market": "SA", "register_number": n, "trade_name_en": f"DRUG{n}", "trade_name_ar": None,
         "ingredients": [], "dosage_form_en": None, "company": None}
        for n in ("1", "2", "3", "4")
    ]  # fmt: skip
    products.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    media = tmp_path / "media"
    media.mkdir()
    images = [
        _image_row("1", "matched"),
        _image_row("2", "needs_review"),
        _image_row("2", "needs_review"),
    ]
    (media / "images.jsonl").write_text("\n".join(json.dumps(r) for r in images), encoding="utf-8")

    code = main(["sfda-images-report", "--products", str(products), "--out", str(media)])

    out = capsys.readouterr().out
    missing = json.loads((media / "missing.json").read_text(encoding="utf-8"))
    assert code == 0
    assert "4 products" in out
    assert "matched: 1" in out
    assert "only needs_review: 1" in out
    assert "no picture: 2" in out
    assert [m["register_number"] for m in missing] == ["3", "4"]


def test_fetching_needs_exactly_one_source_of_pages() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["sfda-images"])
    with pytest.raises(SystemExit):
        parser.parse_args(["sfda-images", "--results", "r.json", "--sitemaps", "dir"])
    assert parser.parse_args(["sfda-images", "--sitemaps", "dir"]).concurrency >= 1


def _details_html(key: str, name: str) -> str:
    fields = {
        "Register Number": key,
        "Trade Name": name,
        "Scientific Name": "ACMEDRONE",
        "Strength": "5",
        "Strength Unit": "mg",
        "Dosage Form": "Tablet",
        "Price": "9.5",
    }
    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in fields.items())
    return f"<table>{rows}</table>"


def _save_details(store: SnapshotStore, key: str, name: str) -> None:
    page = FetchedPage(
        f"https://example.test/en/details_data?id={key}",
        200,
        _details_html(key, name),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.save_page(store.details_path("en", key), page)


def test_new_drugs_are_appended_and_known_ones_are_not_read_again(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "sfda", "run-1")
    _save_details(store, "k1", "ALPHA")
    _save_details(store, "k2", "BETA")
    out = tmp_path / "media" / "products.jsonl"

    first = export_new_products(store, out)
    _save_details(store, "k3", "GAMMA")
    second = export_new_products(store, out)
    third = export_new_products(store, out)

    names = [json.loads(line)["trade_name_en"] for line in out.read_text("utf-8").splitlines()]
    assert (first, second, third) == (2, 1, 0)
    assert names == ["ALPHA", "BETA", "GAMMA"]


def test_the_sync_command_waits_between_cycles_and_needs_a_crawl_run() -> None:
    args = build_parser().parse_args(["sfda-images-sync", "--run-id", "full-1", "--sitemaps", "d"])

    assert args.interval >= 60
    assert args.run_id == "full-1"
    assert args.max_images >= 1
