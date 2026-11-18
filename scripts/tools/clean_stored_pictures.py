"""One-off cleanup: drop stored pictures that are shop logos or listing-page images.

Keeps a backup of images.jsonl, removes the files nothing else uses, and takes the affected
products out of attempts.jsonl so the next cycle tries them again with the stricter rules.
"""

import json
import shutil
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from pharmavique.media.domain.matching import is_listing_page, is_site_asset

MEDIA = Path("data/media")
GENERIC_AFTER = 5  # a picture carried by this many different products is a site asset

images_file = MEDIA / "images.jsonl"
rows = [json.loads(line) for line in images_file.read_text(encoding="utf-8").splitlines() if line.strip()]

products_by_hash: dict[str, set[str]] = defaultdict(set)
for row in rows:
    products_by_hash[row["content_hash"]].add(row["register_number"])

bad: list[dict] = []
good: list[dict] = []
reasons: dict[str, int] = defaultdict(int)
for row in rows:
    if is_listing_page(urlparse(row["page_url"]).path):
        reasons["listing page"] += 1
        bad.append(row)
    elif is_site_asset(row["image_url"]):
        reasons["site asset by name"] += 1
        bad.append(row)
    elif len(products_by_hash[row["content_hash"]]) >= GENERIC_AFTER:
        reasons["same picture on many drugs"] += 1
        bad.append(row)
    else:
        good.append(row)

shutil.copyfile(images_file, MEDIA / "images.jsonl.bak")
images_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in good), encoding="utf-8")

still_used = {r["storage_key"] for r in good}
removed_files = 0
for row in bad:
    if row["storage_key"] not in still_used:
        path = MEDIA / "images" / row["storage_key"]
        if path.is_file():
            path.unlink()
            removed_files += 1

with_picture = {r["register_number"] for r in good}
reopened = {r["register_number"] for r in bad} - with_picture
attempts_file = MEDIA / "attempts.jsonl"
if attempts_file.is_file():
    kept = []
    for line in attempts_file.read_text(encoding="utf-8").splitlines():
        try:
            number = json.loads(line)["register_number"]
        except (ValueError, KeyError):
            continue
        if number not in reopened:
            kept.append(line)
    attempts_file.write_text("".join(line + "\n" for line in kept), encoding="utf-8")

print(f"pictures before: {len(rows)} | removed: {len(bad)} {dict(reasons)} | kept: {len(good)}")
print(f"files deleted: {removed_files} | products reopened for another try: {len(reopened)}")
