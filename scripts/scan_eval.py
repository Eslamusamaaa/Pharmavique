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
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
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
            continue
        matched_lines.add(index)
        tally.read += 1
        numbers = [c.register_number for c in result.lines[index].candidates]
        brands = [
            brand_of(c.trade_name_en or c.trade_name_ar or "")
            for c in result.lines[index].candidates
        ]
        tally.top1 += numbers[:1] == [item.register_number]
        tally.top3 += item.register_number in numbers[:3]
        tally.brand_top1 += any(same_brand(b, item.brand) for b in brands[:1])
        tally.brand_top3 += any(same_brand(b, item.brand) for b in brands[:3])
    tally.extra += len(result.lines) - len(matched_lines)
    read = sum(
        1 for item in items if any(same_brand(r.line.name, item.brand) for r in result.lines)
    )
    print(
        f"  {label}: {read}/{len(items)} read, {len(result.lines)} lines, {tally.seconds[-1]:.0f}s"
    )


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
    parser.add_argument("--folder", type=Path, help="pictures plus labels.csv")
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
    rng = random.Random(args.seed)  # noqa: S311 - picks test pictures, nothing secret
    try:
        if args.folder:
            async with factory() as session:
                for path, numbers in read_labels(args.folder):
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
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
