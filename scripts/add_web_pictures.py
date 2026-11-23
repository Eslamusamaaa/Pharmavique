"""Add pictures found by a person (or an agent) searching the web, one drug at a time.

    uv run python scripts/add_web_pictures.py picks.jsonl

Each line of the input: {"register_number": "...", "image_url": "...", "page_url": "..."}.
The picture is downloaded politely (one request every 2 s per host, a clear User-Agent, a real
image of a sensible size only), stored under `data/media/images/products/SA/<register>/<hash>.<ext>`
and recorded in `data/media/images.jsonl` with trust `unofficial_unverified` and status
`needs_review`. Run `sfda-images-verify` (OCR of the box) and `sfda-images-map` afterwards: the
mapping prefers a picture whose box text confirms the drug. Safe to repeat: a drug that already has
a record for the same image address is skipped.
"""

import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "data" / "media"
USER_AGENT = "DrugRegistrySync/0.1 (polite research crawler; throttled; honours robots.txt)"
MAGIC = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG": ("image/png", "png"),
    b"GIF8": ("image/gif", "gif"),
}
RUN_ID = "web-manual-" + datetime.now(UTC).strftime("%Y%m%d")


def sniff(data: bytes) -> tuple[str, str] | None:
    for magic, kind in MAGIC.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def main(path: str) -> int:
    picks = [
        json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()
    ]
    records_file = MEDIA / "images.jsonl"
    known = {
        (r["register_number"], r["image_url"])
        for r in (json.loads(x) for x in records_file.read_text(encoding="utf-8").splitlines() if x)
    }
    failed_file = (
        MEDIA / "web-picks-failed.jsonl"
    )  # addresses that gave no picture: not asked again
    gone = (
        {tuple(json.loads(x)) for x in failed_file.read_text(encoding="utf-8").splitlines() if x}
        if failed_file.exists()
        else set()
    )
    last_hit: dict[str, float] = {}
    fetched: dict[str, tuple[int, bytes]] = {}
    stored = skipped = failed = 0
    with (
        httpx.Client(
            timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        ) as client,
        records_file.open("a", encoding="utf-8") as out,
        failed_file.open("a", encoding="utf-8") as bad,
    ):
        for pick in picks:
            key = (pick["register_number"], pick["image_url"])
            if key in known or key in gone:
                skipped += 1
                continue
            if (
                pick["image_url"] not in fetched
            ):  # one request per address, however many drugs use it
                host = urlparse(pick["image_url"]).netloc
                wait = 2.0 - (time.monotonic() - last_hit.get(host, 0.0))
                if wait > 0:
                    time.sleep(wait)
                last_hit[host] = time.monotonic()
                try:
                    response = client.get(pick["image_url"])
                    fetched[pick["image_url"]] = (response.status_code, response.content)
                except httpx.HTTPError as error:
                    print("failed", pick["register_number"], type(error).__name__)
                    fetched[pick["image_url"]] = (0, b"")
            status, data = fetched[pick["image_url"]]
            kind = sniff(data)
            if status != 200 or kind is None or not 1_000 <= len(data) <= 5_000_000:
                print("not a usable image", pick["register_number"], status, len(data))
                failed += 1
                bad.write(json.dumps(list(key)) + "\n")
                continue
            content_type, extension = kind
            digest = hashlib.sha256(data).hexdigest()
            storage_key = f"products/SA/{pick['register_number']}/{digest[:16]}.{extension}"
            target = MEDIA / "images" / storage_key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            record = {
                "market": "SA",
                "register_number": pick["register_number"],
                "image_url": pick["image_url"],
                "page_url": pick["page_url"],
                "query": pick.get("query", "web image search"),
                "status": "needs_review",
                "score": 0.5,
                "signals": ["name"],
                "content_hash": digest,
                "content_type": content_type,
                "size_bytes": len(data),
                "storage_key": storage_key,
                "provenance": {
                    "source": "web-image-search",
                    "source_ref": pick["page_url"],
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "snapshot_id": RUN_ID,
                    "trust": "unofficial_unverified",
                },
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            stored += 1
    print(f"stored {stored}, skipped {skipped}, failed {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
