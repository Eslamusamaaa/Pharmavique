"""One polite picture grab for a demo: robots.txt first, stop on any block, validate the bytes.

Usage: python grab_one.py <page_url> <name_for_file> <query>
Not part of the repo. Saves under data/media-demo/ (git-ignored) with a provenance sidecar.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from pharmavique.foundation.http.robots import RobotsPolicy

UA = "DrugRegistrySync/0.1 (polite research crawler; throttled; honours robots.txt)"
PAGE, NAME, QUERY = sys.argv[1], sys.argv[2], sys.argv[3]
BLOCK_MARKERS = ("just a moment", "attention required", "access denied", "captcha")
parsed = urlparse(PAGE)
host = f"{parsed.scheme}://{parsed.netloc}"


def stop(message: str) -> None:
    print("STOP:", message)
    raise SystemExit(1)


with httpx.Client(headers={"User-Agent": UA}, timeout=40, follow_redirects=True) as client:
    robots = client.get(host + "/robots.txt")
    if robots.status_code in (401, 403, 429):
        stop(f"robots.txt answered {robots.status_code}: the site blocks automated clients")
    policy = RobotsPolicy.from_text(robots.text if robots.status_code == 200 else "", UA)
    print("robots.txt", robots.status_code, "| page allowed:", policy.allows(PAGE))
    if not policy.allows(PAGE):
        stop("robots.txt does not allow the page")

    page = client.get(PAGE)
    print("page", page.status_code, len(page.text), "bytes")
    if page.status_code in (401, 403, 429) or any(m in page.text[:3000].lower() for m in BLOCK_MARKERS):
        stop(f"the site answered {page.status_code} / a bot check; not working around it")
    if page.status_code != 200:
        stop(f"unexpected status {page.status_code}")

    soup = BeautifulSoup(page.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    og = soup.find("meta", property="og:image")
    image_url = urljoin(PAGE, str(og["content"])) if og and og.get("content") else None
    print("title:", title[:110])
    print("og:image:", image_url)
    if not image_url:
        stop("no og:image on the page")
    if urlparse(image_url).netloc == parsed.netloc and not policy.allows(image_url):
        stop("robots.txt does not allow the image")

    image = client.get(image_url)
    data, ctype = image.content, image.headers.get("content-type", "")
    magic = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"RIFF": "webp", b"GIF8": "gif"}
    kind = next((v for k, v in magic.items() if data.startswith(k)), None)
    print("image", image.status_code, ctype, len(data), "bytes, magic:", kind)
    if image.status_code != 200 or not ctype.startswith("image/") or kind is None:
        stop("the answer is not a valid image; not saved")
    if not 1_000 <= len(data) <= 5_000_000:
        stop("image size outside the accepted range; not saved")

    digest = hashlib.sha256(data).hexdigest()
    path = f"data/media-demo/{NAME}-{digest[:12]}.{kind}"
    with open(path, "wb") as handle:
        handle.write(data)
    meta = {
        "image_url": image_url,
        "page_url": PAGE,
        "page_title": title,
        "query": QUERY,
        "sha256": digest,
        "content_type": ctype,
        "size_bytes": len(data),
        "fetched_at": datetime.now(UTC).isoformat(),
        "trust": "unofficial_unverified",
        "saved_as": path,
    }
    with open(path + ".json", "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)
    print("saved", path)
