"""Measure how well the scans read medicine names, on labelled photos or on generated pictures.

    uv run python scripts/scan_eval.py --kind shelf --synthetic 4
    uv run python scripts/scan_eval.py --kind prescription --folder data/eval/prescriptions

A folder holds the pictures and a `labels.csv` with one row per picture:

    file,register_numbers
    shelf1.jpg,0902221712;0211234420;1802256914

(the register numbers of the medicines visible in it, separated by `;`). For every picture the tool
runs the same use case the API runs (the real vision model through OpenRouter, then the registry
search) and reports, per medicine that is on the picture:

- read: a line the model read has the same brand name;
- top 1 / top 3: the right register number is the first / one of the first three candidates;
- brand top 1 / top 3: a candidate has the same brand (the registry often has several register
  numbers for one brand: strengths, pack sizes), which is the right answer for a person who
  confirms the exact product afterwards;
- extra lines: lines the model read that are not on the label list (invented or misread names).

`--synthetic N` draws N pictures from real registry names, so no photos are needed to try it. They
are clean printed text, so **the result is an upper bound**: real shelves have glare, angles,
handwriting and clutter. The tool exists so that real labelled photos (Q-32) can be measured the
same way. Nothing is stored: pictures stay in memory unless `--keep DIR` is given.
"""

import argparse
import asyncio
import csv
import io
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import text

from pharmavique.bootstrap.ai import build_scanner
from pharmavique.bootstrap.settings import get_settings
from pharmavique.catalog.application.queries import ReadProductCardsHandler
from pharmavique.catalog.infrastructure.persistence.reader import SqlAlchemyProductReader
from pharmavique.foundation.db.engine import create_engine, create_session_factory
from pharmavique.recognition.application.scan import ScanImage
from pharmavique.recognition.domain.scans import UNCLEAR_DOSE, ScanKind
from pharmavique.search.application.handlers import SearchProductsHandler
from pharmavique.search.infrastructure.postgres import PostgresSearchIndex
from pharmavique.shared_kernel.names import core_name
from pharmavique.shared_kernel.text import normalize_text

FONTS = ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf")
PASTELS = ((255, 236, 179), (200, 230, 201), (187, 222, 251), (248, 187, 208), (225, 190, 231))


@dataclass(frozen=True)
class Item:
    register_number: str
    name: str  # as printed on the picture
    brand: str  # normalized brand, used to compare


THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
PERSON_COLUMNS = ("patient", "name", "doctor", "phone", "id")  # a label file never names a person


@dataclass(frozen=True)
class Label:
    """One labelled photo of the committed answer file (the photo itself stays on this machine)."""

    file: str
    kind: str  # "box", "prescription", "shelf" or "" when the file does not say
    numbers: list[str]  # the register numbers really visible or written
    source_url: str  # where the photo came from, "" when taken by the owner
    notes: str


@dataclass
class Tally:
    expected: int = 0
    read: int = 0
    top1: int = 0
    top3: int = 0
    brand_top1: int = 0
    brand_top3: int = 0
    extra: int = 0
    lines: int = 0
    seconds: list[float] = field(default_factory=list)
    doses_not_unclear: int = 0
    failures: int = 0
    # for each expected medicine whose name was read: (score of the best candidate, was it right)
    scored: list[tuple[float, bool]] = field(default_factory=list)
    # what went wrong, per picture: only file names, register numbers and flags, never text
    cases: list[dict[str, object]] = field(default_factory=list)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def fit(
    draw: ImageDraw.ImageDraw, label: str, width: int, start: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = start
    while size > 10 and draw.textlength(label, font=font(size)) > width:
        size -= 2
    return font(size)


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def draw_box(
    draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, name: str, tint: tuple[int, int, int]
) -> None:
    draw.rectangle((x, y, x + w, y + h), fill=tint, outline=(60, 60, 60), width=3)
    draw.rectangle((x, y, x + w, y + 26), fill=(30, 90, 140))
    label = name.upper()
    words = label.split(" ")
    brand, rest = words[0], " ".join(words[1:])
    draw.text((x + 12, y + 44), brand, font=fit(draw, brand, w - 24, 46), fill=(20, 20, 20))
    if rest:
        draw.text((x + 12, y + 44 + 58), rest, font=fit(draw, rest, w - 24, 28), fill=(40, 40, 40))


def make_picture(kind: ScanKind, items: list[Item], rng: random.Random) -> bytes:
    if kind is ScanKind.BOX:
        image = Image.new("RGB", (900, 600), (235, 235, 235))
        draw = ImageDraw.Draw(image)
        draw_box(draw, 120, 90, 660, 420, items[0].name, rng.choice(PASTELS))
        return png(image)
    if kind is ScanKind.PRESCRIPTION:
        image = Image.new("RGB", (1000, 1300), (252, 252, 250))
        draw = ImageDraw.Draw(image)
        draw.text((60, 50), "Example Clinic", font=font(44), fill=(30, 30, 30))
        draw.text((60, 110), "Rx", font=font(70), fill=(30, 30, 30))
        y = 240
        for number, item in enumerate(items, start=1):
            draw.text(
                (70, y),
                f"{number}. {item.name}",
                font=fit(draw, item.name, 860, 40),
                fill=(20, 20, 60),
            )
            draw.text(
                (110, y + 52), "Sig: 1 tab twice daily for 7 days", font=font(28), fill=(80, 80, 80)
            )
            y += 150
        return png(image)
    image = Image.new("RGB", (1600, 1000), (205, 190, 170))
    draw = ImageDraw.Draw(image)
    columns, box_w, box_h, gap = 4, 340, 300, 40
    for index, item in enumerate(items):
        row, column = divmod(index, columns)
        x, y = 50 + column * (box_w + gap), 60 + row * (box_h + 120)
        draw_box(draw, x, y, box_w, box_h, item.name, rng.choice(PASTELS))
    for row in range(2):
        shelf_y = 60 + row * (box_h + 120) + box_h + 14
        draw.rectangle((20, shelf_y, 1580, shelf_y + 18), fill=(110, 80, 50))
    return png(image)


async def sample_items(engine: object, count: int, rng: random.Random) -> list[Item]:
    """Distinct brands among listed products whose English name has a strength in it."""
    factory = create_session_factory(engine)  # type: ignore[arg-type]
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT register_number, data->'trade_name'->>'en' AS name "
                    "FROM catalog.products "
                    "WHERE listing_status = 'listed' AND data->'trade_name'->>'en' ~ '[0-9]' "
                    "AND length(data->'trade_name'->>'en') BETWEEN 8 AND 28"
                )
            )
        ).all()
    rows = sorted(rows, key=lambda _: rng.random())
    chosen: list[Item] = []
    seen: set[str] = set()
    for row in rows:
        brand = normalize_text(core_name(row.name))
        if brand and brand not in seen and len(brand) >= 4:
            seen.add(brand)
            chosen.append(Item(row.register_number, row.name, brand))
        if len(chosen) == count:
            break
    return chosen


def brand_of(name: str) -> str:
    return normalize_text(core_name(name))


def same_brand(read: str, expected: str) -> bool:
    a, b = brand_of(read), expected
    return bool(a) and (a == b or a in b or b in a)


async def evaluate(
    scanner: ScanImage,
    kind: ScanKind,
    image: bytes,
    media: str,
    items: list[Item],
    tally: Tally,
    label: str,
) -> None:
    started = time.perf_counter()
    try:
        result = await scanner.run(image, media, kind)
    except Exception as error:
        tally.failures += 1
        print(f"  {label}: FAILED ({type(error).__name__}: {error})")
        return
    tally.seconds.append(time.perf_counter() - started)
    tally.expected += len(items)
    tally.lines += len(result.lines)
    tally.doses_not_unclear += sum(
        1 for line in result.lines if kind is ScanKind.PRESCRIPTION and line.dose != UNCLEAR_DOSE
    )
    matched_lines: set[int] = set()
    for item in items:
        index = next(
            (i for i, r in enumerate(result.lines) if same_brand(r.line.name, item.brand)), None
        )
        if index is None:
            tally.cases.append(
                {"file": label, "problem": "name_not_read", "expected": item.register_number}
            )
            continue
        matched_lines.add(index)
        tally.read += 1
        numbers = [c.register_number for c in result.lines[index].candidates]
        best = max((c.score for c in result.lines[index].candidates), default=0.0)
        tally.scored.append((best, numbers[:1] == [item.register_number]))
        if numbers[:1] != [item.register_number]:
            tally.cases.append(
                {
                    "file": label,
                    "problem": "wrong_product",
                    "expected": item.register_number,
                    "top3": numbers[:3],
                    "best_score": round(best, 3),
                }
            )
        brands = [
            brand_of(c.trade_name_en or c.trade_name_ar or "")
            for c in result.lines[index].candidates
        ]
        tally.top1 += numbers[:1] == [item.register_number]
        tally.top3 += item.register_number in numbers[:3]
        tally.brand_top1 += any(same_brand(b, item.brand) for b in brands[:1])
        tally.brand_top3 += any(same_brand(b, item.brand) for b in brands[:3])
    tally.extra += len(result.lines) - len(matched_lines)
    for index in range(len(result.lines)):
        if index not in matched_lines:
            tally.cases.append(
                {
                    "file": label,
                    "problem": "extra_line",
                    "confidence": result.lines[index].confidence.value,
                }
            )
    read = sum(
        1 for item in items if any(same_brand(r.line.name, item.brand) for r in result.lines)
    )
    print(
        f"  {label}: {read}/{len(items)} read, {len(result.lines)} lines, {tally.seconds[-1]:.0f}s"
    )


def sweep(
    scored: list[tuple[float, bool]], thresholds: tuple[float, ...] = THRESHOLDS
) -> list[dict[str, float | int]]:
    """For each threshold: how many read lines would count as confident, how many of those had the
    right product first, and the same for the lines left uncertain. Picking the threshold is a
    trade-off between asking too often and trusting a wrong match."""
    rows: list[dict[str, float | int]] = []
    for threshold in thresholds:
        confident = [right for score, right in scored if score >= threshold]
        uncertain = [right for score, right in scored if score < threshold]
        rows.append(
            {
                "threshold": threshold,
                "confident": len(confident),
                "confident_right": sum(confident),
                "uncertain": len(uncertain),
                "uncertain_right": sum(uncertain),
            }
        )
    return rows


def write_report(
    path: Path, kind: ScanKind, tally: Tally, photos: int, labelled_by: str = ""
) -> None:
    """The result as JSON, to keep in git: numbers, failure cases and the sweep. No image, no text
    that was read, no names of people."""
    data = {
        "date": datetime.now(UTC).date().isoformat(),
        "kind": kind.value,
        "photos": photos,
        "labelled_by": labelled_by,
        "metrics": {
            "expected": tally.expected,
            "read": tally.read,
            "top1": tally.top1,
            "top3": tally.top3,
            "brand_top1": tally.brand_top1,
            "brand_top3": tally.brand_top3,
            "extra_lines": tally.extra,
            "lines": tally.lines,
            "pictures_failed": tally.failures,
            "doses_not_unclear": tally.doses_not_unclear,
        },
        "sweep": sweep(tally.scored),
        "cases": tally.cases,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def report(kind: ScanKind, tally: Tally) -> None:
    def pct(n: int) -> str:
        return f"{n}/{tally.expected} ({n / tally.expected:.0%})" if tally.expected else "n/a"

    print(
        f"\n=== {kind.value}: {tally.expected} medicines on {len(tally.seconds)} pictures "
        f"({tally.failures} pictures failed)"
    )
    print(f"read the name         {pct(tally.read)}")
    print(f"right product, top 1  {pct(tally.top1)}")
    print(f"right product, top 3  {pct(tally.top3)}")
    print(f"same brand, top 1     {pct(tally.brand_top1)}")
    print(f"same brand, top 3     {pct(tally.brand_top3)}")
    print(f"extra lines (not on the picture's list): {tally.extra} of {tally.lines} lines")
    if kind is ScanKind.PRESCRIPTION:
        print(f"doses that were not 'unclear': {tally.doses_not_unclear} (must be 0)")
    if tally.seconds:
        median, slowest = statistics.median(tally.seconds), max(tally.seconds)
        print(f"seconds per picture: median {median:.0f}, max {slowest:.0f}")
    if tally.scored:
        print("\nconfidence threshold: lines called confident, and how many of them were right")
        for row in sweep(tally.scored):
            print(
                f"  {row['threshold']:.2f}: confident {row['confident']} "
                f"({row['confident_right']} right), uncertain {row['uncertain']} "
                f"({row['uncertain_right']} would have been right)"
            )
    for case in tally.cases[:20]:
        print(f"  case: {case}")
    if len(tally.cases) > 20:
        print(f"  ... and {len(tally.cases) - 20} more cases (use --report to keep all of them)")


def read_label_rows(labels: Path) -> list[Label]:
    """The committed answer file: `file,kind,register_numbers,source_url,notes` (all but the file
    and the register numbers are optional). A column that could hold personal data is refused."""
    with labels.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for column in reader.fieldnames or []:
            if column.strip().lower().startswith(PERSON_COLUMNS):
                raise ValueError(f"the label file must not hold personal data: column {column!r}")
        return [
            Label(
                file=row["file"].strip(),
                kind=(row.get("kind") or "").strip(),
                numbers=[n.strip() for n in row["register_numbers"].split(";") if n.strip()],
                source_url=(row.get("source_url") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )
            for row in reader
        ]


def read_labels(folder: Path) -> list[tuple[Path, list[str]]]:
    with (folder / "labels.csv").open(encoding="utf-8", newline="") as handle:
        return [
            (
                folder / row["file"],
                [n.strip() for n in row["register_numbers"].split(";") if n.strip()],
            )
            for row in csv.DictReader(handle)
        ]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--kind", choices=[k.value for k in ScanKind], default="box")
    parser.add_argument("--synthetic", type=int, default=0, help="how many pictures to draw")
    parser.add_argument("--per-picture", type=int, default=0, help="medicines per drawn picture")
    parser.add_argument("--folder", type=Path, help="pictures plus labels.csv (older layout)")
    parser.add_argument(
        "--labels", type=Path, help="the committed answer file, for example eval/scan/labels.csv"
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=Path("data/eval/images"),
        help="where the photos are (stay on this machine, never in git)",
    )
    parser.add_argument("--report", type=Path, help="write the result as JSON (keep it in git)")
    parser.add_argument("--labelled-by", default="", help="who wrote the answers, for the report")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--keep", type=Path, help="save the drawn pictures here")
    args = parser.parse_args()
    kind = ScanKind(args.kind)

    settings = get_settings()
    if settings.database_url is None or settings.openrouter_api_key is None:
        print(
            "set PHARMAVIQUE_DATABASE_URL and PHARMAVIQUE_OPENROUTER_API_KEY first", file=sys.stderr
        )
        return 4
    engine = create_engine(settings.database_url.get_secret_value())
    factory = create_session_factory(engine)
    search = SearchProductsHandler(PostgresSearchIndex(factory))
    catalog = ReadProductCardsHandler(SqlAlchemyProductReader(factory))
    scanner = build_scanner(settings, search=search, catalog=catalog)
    if scanner is None:
        print("no vision provider is configured", file=sys.stderr)
        return 4
    tally = Tally()
    photos = 0
    rng = random.Random(args.seed)  # noqa: S311 - picks test pictures, nothing secret
    try:
        if args.labels:
            async with factory() as session:
                rows = [r for r in read_label_rows(args.labels) if r.kind in ("", kind.value)]
                for label in rows:
                    found = (
                        await session.execute(
                            text(
                                "SELECT register_number, data->'trade_name'->>'en' AS name "
                                "FROM catalog.products WHERE register_number = ANY(:n)"
                            ),
                            {"n": label.numbers},
                        )
                    ).all()
                    items = [
                        Item(r.register_number, r.name or "", brand_of(r.name or "")) for r in found
                    ]
                    path = args.images / label.file
                    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                    await evaluate(
                        scanner, kind, path.read_bytes(), media, items, tally, label.file
                    )
            photos = len(rows)
        elif args.folder:
            async with factory() as session:
                folder_rows = read_labels(args.folder)
                photos = len(folder_rows)
                for path, numbers in folder_rows:
                    rows = (
                        await session.execute(
                            text(
                                "SELECT register_number, data->'trade_name'->>'en' AS name "
                                "FROM catalog.products WHERE register_number = ANY(:n)"
                            ),
                            {"n": numbers},
                        )
                    ).all()
                    items = [
                        Item(r.register_number, r.name or "", brand_of(r.name or "")) for r in rows
                    ]
                    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                    await evaluate(scanner, kind, path.read_bytes(), media, items, tally, path.name)
        else:
            per = (
                args.per_picture
                or {ScanKind.BOX: 1, ScanKind.PRESCRIPTION: 4, ScanKind.SHELF: 8}[kind]
            )
            photos = args.synthetic
            for number in range(args.synthetic):
                items = await sample_items(engine, per, rng)
                image = make_picture(kind, items, rng)
                if args.keep:
                    args.keep.mkdir(parents=True, exist_ok=True)
                    (args.keep / f"{kind.value}-{number + 1}.png").write_bytes(image)
                await evaluate(
                    scanner, kind, image, "image/png", items, tally, f"picture {number + 1}"
                )
    finally:
        await engine.dispose()
    report(kind, tally)
    if args.report:
        write_report(args.report, kind, tally, photos, args.labelled_by)
        print(f"result written to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
