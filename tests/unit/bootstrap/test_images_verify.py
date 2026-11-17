"""Verifying stored pictures with OCR, and the final drug-to-picture mapping. OCR is faked here."""

import json
from pathlib import Path

from pharmavique.bootstrap.images import build_mapping, verify_pictures


def write_products(path: Path) -> None:
    rows = [
        {"market": "SA", "register_number": "1", "trade_name_en": "PANADOL EXTRA TAB",
         "trade_name_ar": "بنادول اكسترا",
         "ingredients": [{"name": "PARACETAMOL", "strength": "500", "unit": "mg"}],
         "dosage_form_en": "Tablet", "company": "Haleon"},
        {"market": "SA", "register_number": "2", "trade_name_en": "BRUFEN 400 MG TAB",
         "trade_name_ar": None,
         "ingredients": [{"name": "IBUPROFEN", "strength": "400", "unit": "mg"}],
         "dosage_form_en": "Tablet", "company": None},
        {"market": "SA", "register_number": "3", "trade_name_en": "RARE INJECTION",
         "trade_name_ar": None, "ingredients": [], "dosage_form_en": "Solution for injection",
         "company": None},
    ]  # fmt: skip
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def image_row(number: str, key: str, status: str = "matched") -> dict[str, object]:
    return {
        "market": "SA",
        "register_number": number,
        "image_url": f"https://shop.example.sa/{key}.jpg",
        "page_url": f"https://shop.example.sa/p/{key}",
        "query": "q",
        "status": status,
        "score": 0.8,
        "signals": ["name"],
        "content_hash": key * 8,
        "content_type": "image/jpeg",
        "size_bytes": 2000,
        "storage_key": f"products/SA/{number}/{key}.jpg",
        "provenance": {
            "source": "web-image-search",
            "source_ref": f"https://shop.example.sa/p/{key}",
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "snapshot_id": "r",
            "trust": "unofficial_unverified",
        },
    }


def setup_media(tmp_path: Path) -> tuple[Path, Path]:
    products = tmp_path / "products.jsonl"
    write_products(products)
    media = tmp_path / "media"
    media.mkdir()
    rows = [image_row("1", "aa"), image_row("2", "bb"), image_row("2", "cc", "needs_review")]
    (media / "images.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return products, media


class FakeOcr:
    def __init__(self, texts: dict[str, str | None]) -> None:
        self.texts = texts
        self.calls: list[list[str]] = []

    def __call__(self, paths: list[Path]) -> dict[Path, str | None]:
        self.calls.append([p.name for p in paths])
        return {p: self.texts.get(p.name) for p in paths}


def test_each_stored_picture_is_read_and_judged_against_its_own_drug(tmp_path: Path) -> None:
    products, media = setup_media(tmp_path)
    ocr = FakeOcr(
        {
            "aa.jpg": "Panadol Extra 24 tablets",
            "bb.jpg": "BRUFEN 400 400 mg Ibuprofen",
            "cc.jpg": "Nurofen Express 200 mg",  # a different product's box
        }
    )

    counts = verify_pictures(products, media, ocr, batch_size=2)

    rows = [
        json.loads(line) for line in (media / "verification.jsonl").read_text("utf-8").splitlines()
    ]
    verdicts = {r["storage_key"].rsplit("/", 1)[1]: r["verdict"] for r in rows}
    assert verdicts == {"aa.jpg": "confirmed", "bb.jpg": "confirmed", "cc.jpg": "not_confirmed"}
    assert counts["confirmed"] == 2
    assert counts["not_confirmed"] == 1
    assert [len(call) for call in ocr.calls] == [2, 1]  # batches of two


def test_pictures_already_verified_are_not_read_again(tmp_path: Path) -> None:
    products, media = setup_media(tmp_path)
    ocr = FakeOcr({"aa.jpg": "Panadol Extra", "bb.jpg": "Brufen 400", "cc.jpg": "x"})
    verify_pictures(products, media, ocr, batch_size=10)
    again = FakeOcr({})

    verify_pictures(products, media, again, batch_size=10)

    assert again.calls == []


def test_a_picture_the_ocr_could_not_open_is_recorded_not_lost(tmp_path: Path) -> None:
    products, media = setup_media(tmp_path)

    counts = verify_pictures(products, media, FakeOcr({}), batch_size=10)

    assert counts["not_confirmed"] == 3
    rows = [
        json.loads(line) for line in (media / "verification.jsonl").read_text("utf-8").splitlines()
    ]
    assert all("ocr_error" in r["signals"] for r in rows)


def test_the_mapping_gives_every_drug_its_best_picture_and_lists_the_rest_as_missing(
    tmp_path: Path,
) -> None:
    products, media = setup_media(tmp_path)
    ocr = FakeOcr({"aa.jpg": "Panadol Extra", "bb.jpg": "Nurofen", "cc.jpg": "Brufen 400 mg"})
    verify_pictures(products, media, ocr, batch_size=10)

    summary = build_mapping(products, media)

    mapping = {
        row["register_number"]: row
        for row in (
            json.loads(line) for line in (media / "mapping.jsonl").read_text("utf-8").splitlines()
        )
    }
    assert summary == {
        "drugs": 3,
        "with_picture": 2,
        "confirmed": 2,
        "unverified": 0,
        "missing": 1,
        "placeholders": 1,
    }
    # drug 2 has two pictures; the one whose box shows the brand wins over the text-only match
    assert mapping["2"]["picture"].endswith("cc.jpg")
    assert mapping["2"]["picture_check"] == "confirmed"
    assert mapping["1"]["scientific_names"] == ["PARACETAMOL"]
    assert mapping["1"]["trade_name_ar"] == "بنادول اكسترا"
    assert mapping["2"]["picture_kind"] == "real"
    # a drug with no real picture gets its dosage form's stand-in, marked as one
    assert mapping["3"]["picture_kind"] == "placeholder"
    assert mapping["3"]["picture_check"] == "no_picture"
    assert mapping["3"]["placeholder_form"] == "injection"
    placeholder = Path(mapping["3"]["picture"])
    assert (placeholder.parent.name, placeholder.name) == ("placeholders", "injection.svg")
    assert (media / "placeholders" / "injection.svg").read_text("utf-8").startswith("<svg")
    assert mapping["3"]["source_page"] is None
